"""Viewer sidecar: the real PMView in headless Chromium, for one trial.

:8080  the PMView origin. PMView sends every call to its own origin, so this server is its backend:
       the PMView build, the agent socket, the project files, and the dev backend for the rest.
:9000  control, for the agent script and the tests: /healthz, /open?project=P, POST /python, /screenshot.

The sidecar owns PMView's agent socket for the whole trial. During `pmai run` it passes pmai's viewer
commands through; before and after, the tests send their own. A browser problem is an infra error
(503 with the reason), never a wrong answer.
"""

import asyncio
import base64
import contextlib
import json
import os
import re
import signal
import time
import uuid
from pathlib import Path

import aiohttp
from aiohttp import web

BACKEND = os.environ.get("PM_BACKEND_URL", "http://computer19.acellera.lan:8002")
AGENT_WS = os.environ.get("AGENT_WS", "ws://main:8100/v1/ws/eval")  # pmai run --viewer-id eval
STATIC = Path(os.environ.get("PMVIEW_STATIC", "/srv/pmview"))  # the PMView build
FILES = Path(os.environ.get("FILES_ROOT", "/files"))  # <project>/<path>, as in a backend bucket
EVIDENCE = Path(os.environ.get("EVIDENCE_DIR", "/logs/artifacts/viewer"))
READY_TIMEOUT = float(os.environ.get("READY_TIMEOUT", 300))  # SwiftShader, Pyodide from CDNs: slow
ORIGIN = "http://localhost:8080"
PING_EVERY = 25  # PMView drops a socket with no message for 31 s
CONNECT_TIMEOUT = 30  # as pmai: a command waits this long for PMView to (re)connect
COMMAND_TIMEOUT = 120  # as pmai
# not passed on by the proxy: aiohttp sets them, or they name this origin
DROP = {"host", "origin", "referer", "connection", "keep-alive", "upgrade", "transfer-encoding",
        "content-length", "content-encoding", "accept-encoding"}
WEBGL2 = """() => {
  const gl = document.createElement("canvas").getContext("webgl2");
  if (!gl) return null;
  const d = gl.getExtension("WEBGL_debug_renderer_info");
  return gl.getParameter(d ? d.UNMASKED_RENDERER_WEBGL : gl.RENDERER);
}"""


def log(event: str, **fields) -> None:
    """One line in events.jsonl (Harbor keeps the artifacts folder) and in the container log."""
    line = json.dumps({"t": round(time.time(), 3), "event": event, **fields})
    print(line, flush=True)
    with open(EVIDENCE / "events.jsonl", "a") as f:
        f.write(line + "\n")


class Unavailable(Exception):
    """The viewer cannot work: an infra error."""


class ToolFailed(Exception):
    """PMView answered a command with an error."""


class Viewer:
    """PMView's agent socket. PMView reconnects when a socket dies, and pmai comes and goes."""

    def __init__(self) -> None:
        self.ws: web.WebSocketResponse | None = None
        self.connected = asyncio.Event()
        self.agent: aiohttp.ClientWebSocketResponse | None = None  # pmai, during `pmai run`
        self.waiting: dict[str, asyncio.Future] = {}  # our own commands

    async def send(self, message: dict) -> None:
        """To PMView. Waits for it to (re)connect, as pmai does."""
        await asyncio.wait_for(self.connected.wait(), CONNECT_TIMEOUT)
        if self.ws is None:
            raise ConnectionError("PMView closed its socket")
        await self.ws.send_json(message)

    async def call(self, tool_name: str, timeout: float = COMMAND_TIMEOUT, **arguments) -> dict:
        """A viewer tool, with the message that pmai sends. Returns PMView's output."""
        command_id = f"eval-{uuid.uuid4().hex}"
        answer = self.waiting[command_id] = asyncio.get_running_loop().create_future()
        command = {"type": "pmview_command", "tool_name": tool_name, "arguments": arguments}
        try:
            await self.send({**command, "chat_id": "eval", "command_id": command_id})
            result = await asyncio.wait_for(answer, timeout)
        finally:
            del self.waiting[command_id]
        if "error" in result:
            raise ToolFailed(result["error"])
        return result.get("output") or {}

    async def from_pmview(self, message: dict) -> None:
        """A result goes to the call that sent the command, else to pmai. A result can come on a
        new socket: PMView answers on the socket it has when the tool ends."""
        if message.get("type") != "pmview_result":
            return  # pong
        answer = self.waiting.get(message.get("command_id"))
        if answer is not None:
            if not answer.done():
                answer.set_result(message)
        elif self.agent is not None:
            with contextlib.suppress(ConnectionError):  # pmai exits: its command is gone with it
                await self.agent.send_json(message)


async def pmview_socket(request: web.Request) -> web.WebSocketResponse:
    """/v3/agent/ws/{id}: PMView's agent socket, and each reconnect. Always accept it: a refused
    handshake (close 1006) starts PMView's auth recovery loop."""
    viewer = request.app[VIEWER]
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    viewer.ws = ws
    viewer.connected.set()
    log("pmview_connected", id=request.match_info["id"])
    try:
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                await viewer.from_pmview(msg.json())
    finally:
        if viewer.ws is ws:
            viewer.ws = None
            viewer.connected.clear()
            log("pmview_disconnected", code=ws.close_code)
    return ws


async def keepalive(viewer: Viewer) -> None:
    """pmai's pings end at the sidecar, and pmai is gone after its turn: ping PMView here."""
    while True:
        await asyncio.sleep(PING_EVERY)
        if viewer.ws is not None:
            with contextlib.suppress(ConnectionError):
                await viewer.ws.send_json({"type": "ping"})


async def bridge(viewer: Viewer, http: aiohttp.ClientSession, url: str) -> None:
    """pmai serves its viewer socket only during `pmai run`: connect whenever it is there, and pass
    its messages to PMView."""
    while True:
        try:
            async with http.ws_connect(url) as agent:
                viewer.agent = agent
                log("pmai_connected")
                try:
                    async for msg in agent:
                        await from_pmai(viewer, agent, msg.json())
                finally:
                    viewer.agent = None
                    log("pmai_disconnected")
        except (aiohttp.ClientError, OSError, TimeoutError):
            pass  # pmai does not serve: before or after `pmai run`
        except Exception as error:  # never stop the bridge
            log("bridge_error", error=repr(error))
        await asyncio.sleep(1)


async def from_pmai(viewer: Viewer, agent: aiohttp.ClientWebSocketResponse, message: dict) -> None:
    if message.get("type") == "ping":
        await agent.send_json({"type": "pong"})
        return
    try:
        await viewer.send(message)  # commands, and the job messages that PMView shows
    except (TimeoutError, ConnectionError):
        if command_id := message.get("command_id"):  # a clear error now, not pmai's 120 s time limit
            error = "The viewer is not connected."
            await agent.send_json({"type": "pmview_result", "command_id": command_id, "error": error})


# ---- :8080, the PMView origin ----------------------------------------------------------------


def local_cookie(header: str) -> str:
    """The backend's cookies can carry its Domain and Secure: drop both, so they stay on this origin."""
    return re.sub(r";\s*(Domain=[^;]*|Secure)(?=;|$)", "", header, flags=re.I)


def project_file(path: str) -> Path | None:
    """`<project>/<path>` in FILES when the project is here (the trial's own). Else None: the backend's."""
    root = FILES.resolve()
    project = path.split("/", 1)[0]
    if not project or not (root / project).is_dir():
        return None
    file = (root / path).resolve()
    if not file.is_relative_to(root / project):
        raise web.HTTPForbidden()
    return file


async def proxy(request: web.Request) -> web.StreamResponse:
    """Every other /v3 call goes to the dev backend, with the browser's cookies: the eval account."""
    headers = {k: v for k, v in request.headers.items() if k.lower() not in DROP}
    body = await request.read() if request.body_exists else None
    try:
        url = BACKEND + request.rel_url.path_qs
        async with request.app[HTTP].request(
            request.method, url, headers=headers, data=body, allow_redirects=False
        ) as upstream:
            response = web.StreamResponse(status=upstream.status, reason=upstream.reason)
            for k, v in upstream.headers.items():
                if k.lower() not in DROP:
                    response.headers.add(k, local_cookie(v) if k.lower() == "set-cookie" else v)
            await response.prepare(request)
            async for chunk in upstream.content.iter_any():  # also server-sent events
                await response.write(chunk)
            await response.write_eof()
            return response
    except aiohttp.ClientError as error:
        log("backend_error", path=request.path, error=repr(error))
        raise web.HTTPBadGateway(text=f"dev backend: {error!r}") from error


async def file_get(request: web.Request) -> web.StreamResponse:
    file = project_file(request.match_info["path"])
    if file is None:
        return await proxy(request)
    if not file.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(file)


async def file_put(request: web.Request) -> web.StreamResponse:
    """pmview_save: a form with one `file`."""
    file = project_file(request.match_info["path"])
    if file is None:
        return await proxy(request)
    form = await request.post()
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(form["file"].file.read())
    log("file_saved", path=request.match_info["path"])
    return web.json_response({})


async def pmview_build(request: web.Request) -> web.FileResponse:
    """The PMView build. Any other path is a page of the app."""
    root = STATIC.resolve()
    file = (root / request.match_info["path"]).resolve()
    return web.FileResponse(file if file.is_relative_to(root) and file.is_file() else root / "index.html")


# ---- the browser ---------------------------------------------------------------------------------


class Browser:
    """Headless Chromium with WebGL on the CPU. `broken` says why it cannot work."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.broken: str | None = None
        self.failed_url: str | None = None  # the last request that failed, for the reason

    def fail(self, reason: str) -> None:
        log("broken", reason=reason)
        self.broken = self.broken or reason

    async def start(self) -> None:
        try:
            await self._start()
        except Exception as error:
            self.fail(f"browser start: {error!r}")
        finally:
            self.started.set()

    async def _start(self) -> None:
        from playwright.async_api import async_playwright  # in the image only, not in the unit tests

        self.playwright = await async_playwright().start()
        chromium = await self.playwright.chromium.launch(
            args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"]  # WebGL on the CPU
        )  # never --disable-gpu: it turns WebGL off
        chromium.on("disconnected", lambda _: self.fail("the browser is gone"))
        # no Playwright trace: it records the login form and the auth cookies
        self.context = await chromium.new_context(viewport={"width": 1280, "height": 800})
        self.page = page = await self.context.new_page()
        page.on("crash", lambda _: self.fail("the page crashed"))
        page.on("pageerror", lambda error: log("page_error", text=str(error)))
        page.on("console", lambda m: m.type == "error" and log("console_error", text=m.text))
        page.on("requestfailed", self.request_failed)
        renderer = await page.evaluate(WEBGL2)
        log("webgl2", renderer=renderer)
        if not renderer:  # a silent fallback draws nothing, with no error
            self.fail("no WebGL2: Mol* cannot draw")
            return
        await self.login()

    def request_failed(self, request) -> None:
        log("request_failed", url=request.url, error=request.failure)
        self.failed_url = request.url

    async def login(self) -> None:
        """Through our own proxy, as PMView does it: the browser keeps the cookies."""
        api = self.context.request
        csrf = (await (await api.get(f"{ORIGIN}/v3/auth/csrf")).json())["csrf_token"]
        form = {"username": os.environ["PM_EMAIL"], "password": os.environ["PM_PASSWORD"]}
        r = await api.post(f"{ORIGIN}/v3/auth/login", form=form, headers={"X-CSRF-Token": csrf})
        if not r.ok:
            self.fail(f"login to {BACKEND}: HTTP {r.status}")

    async def open(self, project: str) -> None:
        await self.context.add_cookies([{"name": "PM_PROJECT", "value": project, "url": ORIGIN}])
        await self.page.goto(ORIGIN, wait_until="commit")  # ready means: PMView runs Python

    async def close(self) -> None:
        """Keep the last frame as evidence. The browser can be dead, or never started."""
        with contextlib.suppress(Exception):
            await self.page.screenshot(path=EVIDENCE / "final.png")
        with contextlib.suppress(Exception):
            await self.playwright.stop()


# ---- :9000, control ----------------------------------------------------------------------------


async def until_ready(viewer: Viewer, browser: Browser, deadline: float) -> None:
    """Until PMView runs Python: its socket is up and Pyodide has started."""
    why = "PMView did not open its agent socket"
    while time.monotonic() < deadline:
        if browser.broken:
            raise Unavailable(browser.broken)
        with contextlib.suppress(TimeoutError, ConnectionError):
            output = await viewer.call("pmview_run_python", timeout=30, code="print('ready')")
            if "ready" in (output.get("stdout") or ""):
                return
            why = output.get("stderr") or "no output from PMView's Python"  # "still starting (40%)"
        await asyncio.sleep(2)
    last = f"; last failed request: {browser.failed_url}" if browser.failed_url else ""
    raise Unavailable(f"not ready after {READY_TIMEOUT:.0f} s: {why}{last}")


async def healthz(request: web.Request) -> web.Response:
    """200 once the browser has started, or failed to: then compose starts the agent container."""
    browser = request.app[BROWSER]
    if not browser.started.is_set():
        raise web.HTTPServiceUnavailable(text="starting")
    return web.Response(text=browser.broken or "ok")


async def open_project(request: web.Request) -> web.Response:
    """The agent script calls this before `pmai run`: PMView on the project, able to run Python.
    Else 503 with the reason, and the script stops."""
    viewer, browser = request.app[VIEWER], request.app[BROWSER]
    start = time.monotonic()
    try:
        await asyncio.wait_for(browser.started.wait(), READY_TIMEOUT)
        if browser.broken:
            raise Unavailable(browser.broken)
        await browser.open(request.query["project"])
        await until_ready(viewer, browser, start + READY_TIMEOUT)
    except Exception as error:
        log("not_ready", reason=str(error) or repr(error))
        raise web.HTTPServiceUnavailable(text=str(error) or repr(error)) from error
    log("ready", project=request.query["project"], seconds=round(time.monotonic() - start, 1))
    return web.Response(text="ready")


async def tool(request: web.Request, tool_name: str, **arguments) -> dict:
    """A viewer tool for the tests: 503 when the viewer cannot answer, 502 when PMView fails."""
    if reason := request.app[BROWSER].broken:
        raise web.HTTPServiceUnavailable(text=reason)
    try:
        return await request.app[VIEWER].call(tool_name, **arguments)
    except (TimeoutError, ConnectionError) as error:
        raise web.HTTPServiceUnavailable(text=f"{tool_name}: no answer from PMView ({error!r})") from error
    except ToolFailed as error:
        raise web.HTTPBadGateway(text=f"{tool_name}: {error}") from error


async def python(request: web.Request) -> web.Response:
    """Body: code for PMView's Python, as the agent's pmview_run_python. Returns stdout, stderr, result."""
    return web.json_response(await tool(request, "pmview_run_python", code=await request.text()))


async def screenshot(request: web.Request) -> web.Response:
    output = await tool(request, "pmview_screenshot", transparent=False)
    if not output.get("success"):
        raise web.HTTPBadGateway(text=f"pmview_screenshot: {output.get('error')}")
    png = base64.b64decode(output["fileContent"].split(",", 1)[-1])  # a data URI
    return web.Response(body=png, content_type="image/png")


# ---- main --------------------------------------------------------------------------------------

VIEWER = web.AppKey("viewer", Viewer)
BROWSER = web.AppKey("browser", Browser)
HTTP = web.AppKey("http", aiohttp.ClientSession)


def origin_app(viewer: Viewer, http: aiohttp.ClientSession) -> web.Application:
    app = web.Application(client_max_size=2**30)  # pmview_save sends whole systems
    app[VIEWER], app[HTTP] = viewer, http
    app.add_routes([
        web.get("/v3/agent/ws/{id}", pmview_socket),
        web.get("/v3/file/{path:.+}", file_get),
        web.put("/v3/file/{path:.+}", file_put),
        web.route("*", "/v3/{path:.*}", proxy),
        web.get("/{path:.*}", pmview_build),
    ])
    return app


def control_app(viewer: Viewer, browser: Browser) -> web.Application:
    app = web.Application()
    app[VIEWER], app[BROWSER] = viewer, browser
    app.add_routes([
        web.get("/healthz", healthz),
        web.get("/open", open_project),
        web.post("/python", python),
        web.get("/screenshot", screenshot),
    ])
    return app


async def main() -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    viewer, browser = Viewer(), Browser()
    stop = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):  # docker compose down: keep the evidence first
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=30)  # server-sent events stay open
    async with aiohttp.ClientSession(cookie_jar=aiohttp.DummyCookieJar(), timeout=timeout) as http:
        runners = []
        for app, port in ((origin_app(viewer, http), 8080), (control_app(viewer, browser), 9000)):
            runners.append(web.AppRunner(app))
            await runners[-1].setup()
            await web.TCPSite(runners[-1], "0.0.0.0", port).start()
        tasks = [asyncio.create_task(keepalive(viewer)), asyncio.create_task(bridge(viewer, http, AGENT_WS))]
        await browser.start()  # after the servers: the login goes through the proxy
        await stop.wait()
        await browser.close()
        for task in tasks:
            task.cancel()
        for runner in runners:
            await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
