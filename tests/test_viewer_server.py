"""viewer/server.py with a fake PMView socket and a fake pmai: no browser."""

import asyncio
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
    at once and answers."""

    url = "wss://site/v3/agent/ws/tab?csrf_token=secret"

    def __init__(self):
        self.seen = []

    def on_message(self, handler):
        self.answer = handler

    def send(self, raw):
        self.seen.append(message := json.loads(raw))
        if message["type"] == "pmview_command":
            output = {"stdout": f"ran {message['arguments']['code']}"}
            reply = json.dumps({**RESULT, "command_id": message["command_id"], "output": output})
            asyncio.get_running_loop().call_soon(self.answer, reply)


def fake_pmai(got: asyncio.Queue, exited: asyncio.Event) -> web.Application:
    """`pmai run --viewer-id eval`: sends one command. When it exits, it closes the socket and refuses
    new ones."""

    async def socket(request):
        if exited.is_set():
            raise web.HTTPServiceUnavailable()
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await ws.send_json({"type": "ping"})
        command = {"tool_name": "pmview_run_python", "arguments": {"code": "agent"}, "chat_id": "c1"}
        await ws.send_json({"type": "pmview_command", **command, "command_id": "pmai-1"})

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
    async with aiohttp.ClientSession() as http:
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

            s.viewer.connect(FakePMView())  # PMView reconnects: the new socket is used
            r = await s.control.post("/python", data="during the turn")
            assert await r.json() == {"stdout": "ran during the turn"}
            assert got.empty()  # the tests' result does not go to pmai
            assert shots == [tmp_path / "steps/000.jpg"]  # pmai's command only

            exited.set()  # pmai exits; the sidecar keeps PMView
            await until(lambda: s.viewer.agent is None)
            r = await s.control.post("/python", data="after the turn")
            assert await r.json() == {"stdout": "ran after the turn"}
            bridge.cancel()
            await pmai.close()

    asyncio.run(scenario())
    events = (tmp_path / "events.jsonl").read_text()
    assert "secret" not in events
    assert '"event": "pmai_result", "tool": "pmview_run_python", "shot": "steps/000.jpg"' in events


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
                                                       "volumes in viewer/compose.yaml")
            s.browser.broken = "no WebGL2: Mol* cannot draw"
            r = await s.control.get("/open", params={"project": "app"})
            assert (r.status, await r.text()) == (503, "no WebGL2: Mol* cannot draw")

    asyncio.run(scenario())


def test_preload(monkeypatch):
    monkeypatch.setattr(server, "PRELOAD", {"pdb_ids": ["1JPZ"], "files": ["pseudo_oxo.pdb"]})

    async def scenario(stdout):
        async with sidecar() as s:
            s.viewer.connect(pmview := FakePMView())

            def answer(raw):  # as PMView answers: the code's output, not the code
                pmview.seen.append(message := json.loads(raw))
                output = {"stdout": stdout} if "code" in message["arguments"] else {"success": True}
                reply = json.dumps({**RESULT, "command_id": message["command_id"], "output": output})
                asyncio.get_running_loop().call_soon(pmview.answer, reply)

            pmview.send = answer
            await server.preload(s.viewer)
            return [(m["tool_name"], m["arguments"]) for m in pmview.seen]

    assert asyncio.run(scenario("Downloading 1JPZ\nloaded\n")) == [
        ("pmview_run_python", {"code": "Molecule('1JPZ').view()\nprint('loaded')"}),
        ("pmview_load", {"files": ["pseudo_oxo.pdb"], "overwrite": True}),
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
