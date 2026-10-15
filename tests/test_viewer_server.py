"""docker/viewer/server.py with a fake PMView socket and a fake pmai: no browser."""

import asyncio
import base64
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import server

RESULT = {"type": "pmview_result"}


class FakePMView:
    """What Playwright gives for PMView's agent socket (a WebSocketRoute): PMView runs each command
    at once and answers. replies: tool name -> the result's fields; else it runs the code."""

    url = "wss://site/v3/agent/ws/tab?csrf_token=secret"

    def __init__(self, **replies):
        self.seen, self.replies = [], replies

    def on_message(self, handler):
        self.answer = handler

    def send(self, raw):
        self.seen.append(message := json.loads(raw))
        if message["type"] == "pmview_command":
            ran = {"output": {"stdout": f"ran {message['arguments'].get('code')}"}}
            reply = {**RESULT, "command_id": message["command_id"]}
            reply |= self.replies.get(message["tool_name"], ran)
            asyncio.get_running_loop().call_soon(self.answer, json.dumps(reply))


def fake_pmai(got: asyncio.Queue, exited: asyncio.Event) -> web.Application:
    """`pmai run --viewer-id eval`: sends a command that changes the view, then one that reads it. When it
    exits, it closes the socket and refuses new ones."""

    async def socket(request):
        if exited.is_set():
            raise web.HTTPServiceUnavailable()
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await ws.send_json({"type": "ping"})
        command = {"tool_name": "pmview_run_python", "arguments": {"code": "agent"}, "chat_id": "c1"}
        await ws.send_json({"type": "pmview_command", **command, "command_id": "pmai-1"})
        read = {"tool_name": "pmview_viewer_state", "arguments": {}, "chat_id": "c1"}
        await ws.send_json({"type": "pmview_command", **read, "command_id": "pmai-2"})

        async def read():
            async for msg in ws:
                await got.put(msg.json())

        reader = asyncio.create_task(read())
        await exited.wait()
        await ws.close()
        await reader
        return ws

    app = web.Application()
    app.add_routes([web.get("/v1/ws/eval", socket)])
    return app


@asynccontextmanager
async def sidecar():
    viewer, browser = server.Viewer(), server.Browser()
    browser.started.set()
    async with asyncio.timeout(10), aiohttp.ClientSession() as http:  # a hang fails the test
        control = TestClient(TestServer(server.control_app(viewer, browser)))
        await control.start_server()
        tasks = [asyncio.create_task(server.keepalive(viewer)), asyncio.create_task(viewer.from_pmview())]
        try:
            yield SimpleNamespace(viewer=viewer, browser=browser, http=http, control=control)
        finally:
            for task in tasks:
                task.cancel()
            await control.close()


@pytest.fixture(autouse=True)
def folders(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "EVIDENCE", tmp_path)
    monkeypatch.setattr(server, "FILES", tmp_path / "files")
    (tmp_path / "files" / "app").mkdir(parents=True)


async def until(condition, timeout=5.0):
    async with asyncio.timeout(timeout):
        while not condition():
            await asyncio.sleep(0.01)


def test_pings_pmview(monkeypatch):
    monkeypatch.setattr(server, "PING_EVERY", 0.05)  # PMView drops a socket with no message for 31 s

    async def scenario():
        async with sidecar() as s:
            s.viewer.connect(pmview := FakePMView())
            await until(lambda: {"type": "ping"} in pmview.seen)

    asyncio.run(scenario())


def test_each_result_goes_to_its_sender(tmp_path):
    async def scenario():
        async with sidecar() as s:
            s.viewer.connect(FakePMView())
            shots = []
            s.viewer.shoot = lambda path: asyncio.sleep(0, shots.append(path))  # after pmai's commands
            got, exited = asyncio.Queue(), asyncio.Event()
            pmai = TestServer(fake_pmai(got, exited))
            await pmai.start_server()
            bridge = asyncio.create_task(server.bridge(s.viewer, s.http, str(pmai.make_url("/v1/ws/eval"))))

            assert await asyncio.wait_for(got.get(), 5) == {"type": "pong"}
            result = await asyncio.wait_for(got.get(), 5)
            assert result == {**RESULT, "command_id": "pmai-1", "output": {"stdout": "ran agent"}}
            assert (await asyncio.wait_for(got.get(), 5))["command_id"] == "pmai-2"

            s.viewer.connect(FakePMView())  # PMView reconnects: the new socket is used
            r = await s.control.post("/python", data="during the turn")
            assert await r.json() == {"stdout": "ran during the turn"}
            assert got.empty()  # the tests' result does not go to pmai
            assert shots == [tmp_path / "steps/000.jpg"]  # pmai's command that changes the view only

            exited.set()  # pmai exits; the sidecar keeps PMView
            await until(lambda: s.viewer.agent is None)
            r = await s.control.post("/python", data="after the turn")
            assert await r.json() == {"stdout": "ran after the turn"}
            bridge.cancel()
            await pmai.close()

    asyncio.run(scenario())
    events = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert "secret" not in str(events)
    assert [(e["tool"], e["shot"]) for e in events if e["event"] == "pmai_result"] == [
        ("pmview_run_python", "steps/000.jpg"), ("pmview_viewer_state", None)]


def test_shoots_only_a_changed_page(tmp_path, monkeypatch):
    real_sleep = asyncio.sleep
    monkeypatch.setattr(asyncio, "sleep", lambda delay, result=None: real_sleep(0, result))
    pages = iter([b"a", b"a", b"b", b"a"])
    browser = server.Browser()
    browser.page = SimpleNamespace(screenshot=lambda **_: real_sleep(0, next(pages)))

    async def four_commands():
        for i in range(4):
            await browser.shoot(tmp_path / f"steps/{i:03}.jpg")

    asyncio.run(four_commands())
    assert sorted(p.name for p in (tmp_path / "steps").iterdir()) == ["000.jpg", "002.jpg", "003.jpg"]


def test_no_pmview_is_an_infra_error(monkeypatch):
    monkeypatch.setattr(server, "CONNECT_TIMEOUT", 0.1)

    async def scenario():
        async with sidecar() as s:
            r = await s.control.post("/python", data="1")
            assert r.status == 503
            r = await s.control.get("/open", params={"project": "other"})  # not in the shared volume
            assert r.status == 503
            r = await s.control.post("/python", data="1")  # after a failed /open: no wait, the reason
            assert (r.status, await r.text()) == (503, f"no project other in {server.FILES}: see the "
                                                       "volumes in compose.yaml")
            s.browser.broken = "no WebGL2: Mol* cannot draw"
            r = await s.control.get("/open", params={"project": "app"})
            assert (r.status, await r.text()) == (503, "no WebGL2: Mol* cannot draw")

    asyncio.run(scenario())


def test_control_api():
    """/open waits until PMView runs Python. /screenshot gives PMView's data URI as PNG. A PMView tool
    that fails is a 502: the test fails, the trial is not an infra error."""
    png = "data:image/png;base64," + base64.b64encode(b"PNG").decode()

    async def scenario():
        async with sidecar() as s:
            s.viewer.connect(pmview := FakePMView(
                pmview_screenshot={"output": {"success": True, "fileContent": png}}))
            s.browser.open = lambda project: asyncio.sleep(0)
            s.browser.page = SimpleNamespace(evaluate=lambda script: asyncio.sleep(0, ["main.js"]))
            r = await s.control.get("/open", params={"project": "app"})
            assert (r.status, await r.text()) == (200, "ready")
            r = await s.control.get("/screenshot")
            assert (r.status, await r.read()) == (200, b"PNG")

            pmview.replies["pmview_screenshot"] = {"output": {"success": False, "error": "no canvas"}}
            r = await s.control.get("/screenshot")
            assert (r.status, await r.text()) == (502, "pmview_screenshot: no canvas")
            pmview.replies["pmview_run_python"] = {"error": "Pyodide crashed"}
            r = await s.control.post("/python", data="1")
            assert (r.status, await r.text()) == (502, "pmview_run_python: Pyodide crashed")

    asyncio.run(scenario())


def test_preload(monkeypatch):
    monkeypatch.setattr(server, "PRELOAD", {"pdb_ids": ["1JPZ"]})

    async def scenario(stdout):
        async with sidecar() as s:
            s.viewer.connect(pmview := FakePMView(pmview_run_python={"output": {"stdout": stdout}}))
            await server.preload(s.viewer)
            return [(m["tool_name"], m["arguments"]) for m in pmview.seen]

    assert asyncio.run(scenario("Downloading 1JPZ\nloaded\n")) == [
        ("pmview_run_python", {"code": "Molecule('1JPZ').view()\nprint('loaded')"}),
    ]
    with pytest.raises(server.Unavailable, match="preload 1JPZ"):  # Molecule failed: no "loaded" line
        asyncio.run(scenario(""))


class FakeRoute:
    """What Playwright gives for a /v3/file/ request."""

    def __init__(self, method, url, body=None, content_type=""):
        self.request = SimpleNamespace(method=method, url=url, post_data_buffer=body,
                                       headers={"content-type": content_type})
        self.done = None

    async def fulfill(self, status=200, path=None, json=None):
        self.done = (status, path.read_bytes() if path else json)

    async def fallback(self):
        self.done = "site"


def test_project_files(tmp_path):
    data = b"ATOM\r\n\x00\xff\nEND\n"  # bytes as they are: no line ending or encoding change
    body = (b'--XyZ\r\nContent-Disposition: form-data; name="file"; filename="a.pdb"\r\n'
            b"Content-Type: application/octet-stream\r\n\r\n" + data + b"\r\n--XyZ--\r\n")
    site, form = "https://site/v3/file", "multipart/form-data; boundary=XyZ"

    async def run(*args, **kwargs):
        await server.project_files(route := FakeRoute(*args, **kwargs))
        return route.done

    async def scenario():
        assert await run("PUT", f"{site}/app/out/a%20b.pdb", body, form) == (200, {})
        assert (tmp_path / "files/app/out/a b.pdb").read_bytes() == data
        assert await run("GET", f"{site}/app/out/a%20b.pdb?t=1") == (200, data)
        assert await run("GET", f"{site}/app/none.pdb") == (404, None)
        assert await run("GET", f"{site}/other/a.pdb") == "site"  # not this trial's project
        assert await run("GET", f"{site}/app/%2e%2e/%2e%2e/secret") == (403, None)

    asyncio.run(scenario())


def test_pmview_build(tmp_path, monkeypatch):
    build = tmp_path / "build"
    monkeypatch.setattr(server, "BUILD", build)
    (build / "static/assets").mkdir(parents=True)
    (build / "index.html").write_bytes(b"page")
    (build / "static/assets/utils.py").write_bytes(b"code")
    (tmp_path / "secret.txt").write_bytes(b"secret")  # next to the build: never served

    async def run(path):
        await server.pmview_build(route := FakeRoute("GET", f"https://site{path}"))
        return route.done

    async def scenario():
        assert await run("/") == (200, b"page")
        assert await run("/projects/abc") == (200, b"page")  # an app route
        assert await run("/static/assets/utils.py?v=2") == (200, b"code")
        assert await run("/static/assets/none.whl") == "site"
        assert await run("/config.js") == "site"  # the site's runtime config
        assert await run("/v3/auth/csrf") == "site"
        assert await run("/%2e%2e/secret.txt") == "site"

    asyncio.run(scenario())


def test_project_list(tmp_path):
    (tmp_path / "files/other").mkdir()

    class ListRoute(FakeRoute):
        def __init__(self, site):
            super().__init__("GET", "https://site/v3/prefixes")
            self.site = site

        async def fetch(self):
            return SimpleNamespace(ok=self.site is not None, json=lambda: asyncio.sleep(0, self.site))

        async def fulfill(self, response=None, json=None):
            self.done = json if response.ok else "site error"

    async def run(site):
        await server.project_list(route := ListRoute(site))
        return route.done

    async def scenario():
        assert sorted(await run(["mine", "other"])) == ["app", "mine", "other"]  # each trial project once
        assert await run(None) == "site error"  # passed on: PMView then keeps its project

    asyncio.run(scenario())
