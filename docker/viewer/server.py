"""Viewer sidecar: the deployed PMView site in headless Chromium, for one trial.

The browser opens the site (PMVIEW_URL) and logs in as the eval account. Playwright takes these
things away from the site:
- PMView's agent socket (/v3/agent/ws/...): PMView talks to this sidecar, not to the site's agent.
- the trial project's files (/v3/file/<project>/...): the shared project folder, not the site's bucket.
- the account's project list (/v3/prefixes): the site's list and the trial projects.
- PMView itself, if the image has a PMView build (make viewer PMVIEW=<checkout>): the page, its
  scripts and its Python come from the build; the backend (/v3/...) and config.js from the site.

:9000  control, for the agent script and the tests: /healthz, /open?project=P, POST /python, /screenshot.
/open also loads the task's structures (VIEWER_PRELOAD), as the agent loads them.

The sidecar owns PMView's agent socket for the whole trial. During `pmai run` it passes pmai's viewer
commands through; before and after, the tests send their own. A browser problem is an infra error
(503 with the reason), never a wrong answer.
"""

import asyncio
import base64
import contextlib
import email.policy
import json
import os
import signal
import time
import urllib.parse
import uuid
from pathlib import Path

import aiohttp
from aiohttp import web

SITE = (os.environ.get("PMVIEW_URL") or "https://acellera.playmolecule.ai").rstrip("/")  # empty: default
# pmai run --viewer-id eval. compose.yaml sets it for a trial; the default is for a hand run (plan 5.8)
AGENT_WS = os.environ.get("AGENT_WS", "ws://localhost:8100/v1/ws/eval")
PRELOAD = json.loads(os.environ.get("VIEWER_PRELOAD") or "{}")  # the task's start: {"pdb_ids", "files"}
FILES = Path(os.environ.get("FILES_ROOT", "/files"))  # <project>/<path>, as in a backend bucket
EVIDENCE = Path(os.environ.get("EVIDENCE_DIR", "/logs/artifacts/viewer"))
BUILD = Path(os.environ.get("PMVIEW_BUILD", "/srv/pmview"))  # no index.html: PMView from the site
READY_TIMEOUT = float(os.environ.get("READY_TIMEOUT", 300))  # SwiftShader, Pyodide from CDNs: slow
PING_EVERY = 25  # PMView drops a socket with no message for 31 s
CONNECT_TIMEOUT = 30  # as pmai: a command waits this long for PMView to connect
COMMAND_TIMEOUT = 120  # as pmai
READS = {"pmview_viewer_state", "pmview_screenshot"}  # pmai's commands that do not change the page
WEBGL2 = """() => {
  const gl = document.createElement("canvas").getContext("webgl2");
  if (!gl) return null;
  const d = gl.getExtension("WEBGL_debug_renderer_info");
  return gl.getParameter(d ? d.UNMASKED_RENDERER_WEBGL : gl.RENDERER);
}"""
LOGIN = """async ([username, password]) => {
  const csrf = (await (await fetch("/v3/auth/csrf")).json()).csrf_token;
  const body = new URLSearchParams({username, password});
  return (await fetch("/v3/auth/login", {method: "POST", headers: {"X-CSRF-Token": csrf}, body})).status;
}"""
SCRIPTS = "() => [...document.scripts].map(s => s.src).filter(Boolean)"  # the deployed PMView build


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
        self.ws = None  # Playwright's WebSocketRoute: the newest socket from PMView
        self.connected = asyncio.Event()
        self.inbox: asyncio.Queue = asyncio.Queue()  # PMView's messages, from all its sockets
        self.agent: aiohttp.ClientWebSocketResponse | None = None  # pmai, during `pmai run`
        self.waiting: dict[str, asyncio.Future] = {}  # our own commands
        self.tools: dict[str, str] = {}  # pmai's commands: command_id -> tool name
        self.shoot = None  # Browser.shoot: the page after each of pmai's commands (main sets it)
        self.shots: list[asyncio.Task] = []

    def connect(self, ws) -> None:
        """Playwright gives us each socket that PMView opens. Nothing goes to the site's agent.
        No on_close: Playwright 1.58 fails on a close with no reason. A dead socket gives a time out."""
        self.ws = ws
        self.connected.set()
        ws.on_message(self.inbox.put_nowait)
        log("pmview_connected", url=ws.url.split("?")[0])  # the query has the csrf token

    async def send(self, message: dict) -> None:
        """To PMView. Waits for it to connect, as pmai does."""
        await asyncio.wait_for(self.connected.wait(), CONNECT_TIMEOUT)
        self.ws.send(json.dumps(message))

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

    async def from_pmview(self) -> None:
        """A result goes to the call that sent the command, else to pmai. A result can come on a
        new socket: PMView answers on the socket it has when the tool ends."""
        while True:
            message = json.loads(await self.inbox.get())
            if message.get("type") != "pmview_result":
                continue  # pong
            answer = self.waiting.get(message.get("command_id"))
            if answer is not None:
                if not answer.done():
                    answer.set_result(message)
            elif self.agent is not None:
                tool = self.tools.pop(message.get("command_id"), None)
                # a read leaves the page as it was: only the first command of the trial shows the start
                shoot = self.shoot and not (tool in READS and self.shots)
                shot = f"steps/{len(self.shots):03}.jpg" if shoot else None
                # logged before pmai gets it, so before agent.db has the step: trajectory.py needs the order
                log("pmai_result", tool=tool, shot=shot)
                with contextlib.suppress(ConnectionError):  # pmai exits: its command is gone with it
                    await self.agent.send_json(message)
                if shot:
                    self.shots.append(asyncio.create_task(self.shoot(EVIDENCE / shot)))


async def keepalive(viewer: Viewer) -> None:
    """pmai's pings end at the sidecar, and pmai is gone after its turn: ping PMView here."""
    while True:
        await asyncio.sleep(PING_EVERY)
        if viewer.ws is not None:
            viewer.ws.send(json.dumps({"type": "ping"}))


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
    if message.get("type") == "pmview_command":
        viewer.tools[message.get("command_id")] = message.get("tool_name")
    try:
        await viewer.send(message)  # commands, and the job messages that PMView shows
    except TimeoutError:
        if command_id := message.get("command_id"):  # a clear error now, not pmai's 120 s time limit
            error = "The viewer is not connected."
            await agent.send_json({"type": "pmview_result", "command_id": command_id, "error": error})


# ---- the trial's project files -------------------------------------------------------------------


def form_file(content_type: str, body: bytes) -> bytes:
    """The `file` field of a multipart form (pmview_save)."""
    form = email.message_from_bytes(f"Content-Type: {content_type}\r\n\r\n".encode() + body,
                                    policy=email.policy.HTTP)
    for part in form.iter_parts():
        if part.get_param("name", header="content-disposition") == "file":
            return part.get_payload(decode=True)
    raise ValueError("no file field in the form")


async def project_files(route) -> None:
    """Playwright route for /v3/file/**: GET (pmview_load) and PUT (pmview_save) in the trial project,
    `<project>/<path>` in FILES. Another project is the site's."""
    request = route.request
    path = urllib.parse.unquote(urllib.parse.urlsplit(request.url).path).removeprefix("/v3/file/")
    root, name = FILES.resolve(), path.split("/", 1)[0]
    if not name or not (root / name).is_dir():
        return await route.fallback()
    file = (root / path).resolve()
    if not file.is_relative_to(root / name):
        return await route.fulfill(status=403)
    if request.method not in ("GET", "PUT"):
        return await route.fallback()
    if request.method == "GET":
        return await (route.fulfill(path=file) if file.is_file() else route.fulfill(status=404))
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(form_file(request.headers["content-type"], request.post_data_buffer or b""))
    log("file_saved", path=path)
    await route.fulfill(json={})


async def project_list(route) -> None:
    """Playwright route for /v3/prefixes, the account's projects: the site's list and the trial projects.
    PMView opens the account's default project when its project is not in this list."""
    response = await route.fetch()
    if not response.ok:
        return await route.fulfill(response=response)
    projects = await response.json()
    trial = [p.name for p in FILES.iterdir() if p.is_dir() and p.name not in projects]
    await route.fulfill(response=response, json=projects + trial)


async def pmview_build(route) -> None:
    """Playwright route for the whole site: PMView's files from BUILD. The backend (/v3/...), the
    runtime config (config.js) and a file the build does not have come from the site."""
    path = urllib.parse.unquote(urllib.parse.urlsplit(route.request.url).path).lstrip("/")
    if path.startswith("v3/") or path == "config.js":
        return await route.fallback()
    file = (BUILD / path).resolve()
    if not file.is_file() and "." not in path.rsplit("/", 1)[-1]:
        file = BUILD / "index.html"  # an app route, or the site root
    if not file.is_file() or not file.is_relative_to(BUILD.resolve()):
        return await route.fallback()
    await route.fulfill(path=file)


# ---- the browser ---------------------------------------------------------------------------------


class Browser:
    """Headless Chromium with WebGL on the CPU. `broken` says why it cannot work."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.broken: str | None = None
        self.failed_url: str | None = None  # the last request that failed, for the reason
        self.last_shot = b""

    def fail(self, reason: str) -> None:
        log("broken", reason=reason)
        self.broken = self.broken or reason

    async def start(self, viewer: Viewer) -> None:
        try:
            await self._start(viewer)
        except Exception as error:
            self.fail(f"browser start: {error!r}")
        finally:
            self.started.set()

    async def _start(self, viewer: Viewer) -> None:
        from playwright.async_api import async_playwright  # in the image only, not in the unit tests

        self.playwright = await async_playwright().start()
        chromium = await self.playwright.chromium.launch(
            args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"]  # WebGL on the CPU
        )  # never --disable-gpu: it turns WebGL off
        chromium.on("disconnected", lambda _: self.fail("the browser is gone"))
        # no Playwright trace: it records the login form and the auth cookies
        # service workers blocked: a request that a service worker answers skips the routes
        # a QHD screen: the canvas (half the window) is wide enough for PMView to capture it as it is
        self.context = await chromium.new_context(viewport={"width": 2560, "height": 1440},
                                                  service_workers="block")
        if (BUILD / "index.html").is_file():  # first: the routes added later go before it
            await self.context.route(f"{SITE}/**", pmview_build)
        await self.context.route_web_socket("**/v3/agent/ws/**", viewer.connect)
        await self.context.route("**/v3/file/**", project_files)
        await self.context.route("**/v3/prefixes", project_list)
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
        """In the page, so Chromium keeps the cookies. Playwright's own HTTP client cannot verify the dev
        site: it sends no intermediate certificate. A small JSON page of the site, not the whole app."""
        await self.page.goto(f"{SITE}/v3/auth/csrf")
        status = await self.page.evaluate(LOGIN, [os.environ["PM_EMAIL"], os.environ["PM_PASSWORD"]])
        if status != 200:
            self.fail(f"login to {SITE}: HTTP {status}")

    async def open(self, project: str) -> None:
        await self.context.add_cookies([{"name": "PM_PROJECT", "value": project, "url": SITE}])
        await self.page.goto(SITE, wait_until="commit")  # ready means: PMView runs Python

    async def shoot(self, path: Path) -> None:
        """The page after one of pmai's commands, for the trace in `make view` (trajectory.py).
        Only a changed page: most commands (state, prints, analysis) do not change the view."""
        await asyncio.sleep(1)  # PMView draws a change after the command returns
        with contextlib.suppress(Exception):  # evidence only
            shot = await self.page.screenshot(type="jpeg", quality=70)
            if shot != self.last_shot:
                self.last_shot = shot
                path.parent.mkdir(exist_ok=True)
                path.write_bytes(shot)

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
        with contextlib.suppress(TimeoutError):
            output = await viewer.call("pmview_run_python", timeout=30, code="print('ready')")
            if "ready" in (output.get("stdout") or ""):
                return
            # "The Python engine is still starting (20%)..."
            why = output.get("error") or output.get("stderr") or "no output from PMView's Python"
        await asyncio.sleep(2)
    last = f"; last failed request: {browser.failed_url}" if browser.failed_url else ""
    raise Unavailable(f"not ready after {READY_TIMEOUT:.0f} s: {why}{last}")


async def preload(viewer: Viewer) -> None:
    """As the agent loads them: a PDB id with Molecule (the pmview skill's way), files with pmview_load."""
    for pdb in PRELOAD.get("pdb_ids", []):
        output = await viewer.call("pmview_run_python", code=f"Molecule({pdb!r}).view()\nprint('loaded')")
        if (output.get("stdout") or "").split()[-1:] != ["loaded"]:  # other output can come first
            raise Unavailable(f"preload {pdb}: {output}")
        log("preloaded", pdb=pdb)
    if files := PRELOAD.get("files"):
        output = await viewer.call("pmview_load", files=files, overwrite=True)
        if not output.get("success"):
            raise Unavailable(f"preload {files}: {output}")
        log("preloaded", files=files)


async def healthz(request: web.Request) -> web.Response:
    """200 once the browser has started, or failed to: then compose starts the agent container."""
    browser = request.app[BROWSER]
    if not browser.started.is_set():
        raise web.HTTPServiceUnavailable(text="starting")
    return web.Response(text=browser.broken or "ok")


async def open_project(request: web.Request) -> web.Response:
    """The agent script calls this before `pmai run`: PMView on the project, able to run Python.
    Else 503 with the reason, and the script stops."""
    viewer, browser, project = request.app[VIEWER], request.app[BROWSER], request.query["project"]
    start = time.monotonic()
    try:
        if not (FILES / project).is_dir():  # else the project files would come from the site
            raise Unavailable(f"no project {project} in {FILES}: see the volumes in compose.yaml")
        await asyncio.wait_for(browser.started.wait(), READY_TIMEOUT)
        if browser.broken:
            raise Unavailable(browser.broken)
        await browser.open(project)
        await until_ready(viewer, browser, deadline := start + READY_TIMEOUT)
        try:  # within READY_TIMEOUT too: the agent script waits 600 s for all of /open
            await asyncio.wait_for(preload(viewer), deadline - time.monotonic())
        except TimeoutError:
            raise Unavailable(f"preload not done after {READY_TIMEOUT:.0f} s") from None
        scripts = await browser.page.evaluate(SCRIPTS)
    except Exception as error:
        browser.fail(str(error) or repr(error))  # the tests then get a 503 too, not a viewer with no project
        raise web.HTTPServiceUnavailable(text=browser.broken) from error
    seconds = round(time.monotonic() - start, 1)
    version = BUILD / "VERSION"  # make viewer writes it: the PMView commit of the build
    pmview = version.read_text().strip() if version.is_file() else "the site's"
    log("ready", project=project, seconds=seconds, site=SITE, pmview=pmview, scripts=scripts)
    return web.Response(text="ready")


async def tool(request: web.Request, tool_name: str, **arguments) -> dict:
    """A viewer tool for the tests: 503 when the viewer cannot answer, 502 when PMView fails."""
    if reason := request.app[BROWSER].broken:
        raise web.HTTPServiceUnavailable(text=reason)
    try:
        return await request.app[VIEWER].call(tool_name, **arguments)
    except TimeoutError as error:
        raise web.HTTPServiceUnavailable(text=f"{tool_name}: no answer from PMView ({error!r})") from error
    except ToolFailed as error:
        raise web.HTTPBadGateway(text=f"{tool_name}: {error}") from error


async def python(request: web.Request) -> web.Response:
    """Body: code for PMView's Python, as the agent's pmview_python. Returns stdout, stderr, result."""
    return web.json_response(await tool(request, "pmview_run_python", code=await request.text()))


async def screenshot(request: web.Request) -> web.Response:
    output = await tool(request, "pmview_screenshot", transparent=False, resolution="viewport")
    if not output.get("success"):
        raise web.HTTPBadGateway(text=f"pmview_screenshot: {output.get('error')}")
    png = base64.b64decode(output["fileContent"].split(",", 1)[-1])  # a data URI
    return web.Response(body=png, content_type="image/png")


# ---- main --------------------------------------------------------------------------------------

VIEWER = web.AppKey("viewer", Viewer)
BROWSER = web.AppKey("browser", Browser)


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
    os.umask(0)  # root here can be nobody on the host (NFS): the host user must still delete the evidence
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    viewer, browser = Viewer(), Browser()
    viewer.shoot = browser.shoot
    stop = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):  # docker compose down: keep the evidence first
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=30)  # the pmai socket stays open for the turn
    async with aiohttp.ClientSession(timeout=timeout) as http:
        runner = web.AppRunner(control_app(viewer, browser))
        await runner.setup()
        await web.TCPSite(runner, "0.0.0.0", 9000).start()
        tasks = [asyncio.create_task(t) for t in
                 (viewer.from_pmview(), keepalive(viewer), bridge(viewer, http, AGENT_WS))]
        await browser.start(viewer)
        await stop.wait()
        await browser.close()
        for task in tasks:
            task.cancel()
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
