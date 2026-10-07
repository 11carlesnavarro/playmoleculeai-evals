"""viewer/server.py with a fake PMView socket and a fake pmai: no browser."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import server

RESULT = {"type": "pmview_result"}


async def fake_pmview(url, seen: list) -> None:
    """PMView's end of the agent socket: runs each command at once and answers."""
    async with aiohttp.ClientSession() as http, http.ws_connect(url) as ws:
        async for msg in ws:
            seen.append(message := msg.json())
            if message["type"] == "pmview_command":
                output = {"stdout": f"ran {message['arguments']['code']}"}
                await ws.send_json({**RESULT, "command_id": message["command_id"], "output": output})


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
        origin = TestServer(server.origin_app(viewer, http))
        control = TestClient(TestServer(server.control_app(viewer, browser)))
        await origin.start_server()
        await control.start_server()
        keepalive = asyncio.create_task(server.keepalive(viewer))
        try:
            yield SimpleNamespace(viewer=viewer, browser=browser, http=http, origin=origin, control=control)
        finally:
            keepalive.cancel()
            await control.close()
            await origin.close()


@pytest.fixture(autouse=True)
def folders(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "EVIDENCE", tmp_path)
    monkeypatch.setattr(server, "FILES", tmp_path / "files")
    (tmp_path / "files" / "app").mkdir(parents=True)


async def until(condition, timeout=5.0):
    async with asyncio.timeout(timeout):
        while not condition():
            await asyncio.sleep(0.01)


def test_pings_pmview(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "PING_EVERY", 0.05)  # PMView drops a socket with no message for 31 s

    async def scenario():
        async with sidecar() as s:
            seen = []
            pmview = asyncio.create_task(fake_pmview(s.origin.make_url("/v3/agent/ws/tab"), seen))
            await until(lambda: {"type": "ping"} in seen)
            pmview.cancel()

    asyncio.run(scenario())


def test_each_result_goes_to_its_sender(tmp_path):
    async def scenario():
        async with sidecar() as s:
            pmview = asyncio.create_task(fake_pmview(s.origin.make_url("/v3/agent/ws/tab"), []))
            got, exited = asyncio.Queue(), asyncio.Event()
            pmai = TestServer(fake_pmai(got, exited))
            await pmai.start_server()
            bridge = asyncio.create_task(server.bridge(s.viewer, s.http, str(pmai.make_url("/v1/ws/eval"))))

            assert await asyncio.wait_for(got.get(), 5) == {"type": "pong"}
            result = await asyncio.wait_for(got.get(), 5)
            assert result == {**RESULT, "command_id": "pmai-1", "output": {"stdout": "ran agent"}}

            r = await s.control.post("/python", data="during the turn")
            assert await r.json() == {"stdout": "ran during the turn"}
            assert got.empty()  # the tests' result does not go to pmai

            exited.set()  # pmai exits; the sidecar keeps PMView
            await until(lambda: s.viewer.agent is None)
            r = await s.control.post("/python", data="after the turn")
            assert await r.json() == {"stdout": "ran after the turn"}
            bridge.cancel()
            pmview.cancel()
            await pmai.close()

    asyncio.run(scenario())


def test_no_pmview_is_an_infra_error(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "CONNECT_TIMEOUT", 0.1)

    async def scenario():
        async with sidecar() as s:
            r = await s.control.post("/python", data="1")
            assert r.status == 503
            s.browser.broken = "no WebGL2: Mol* cannot draw"
            r = await s.control.get("/open", params={"project": "app"})
            assert (r.status, await r.text()) == (503, "no WebGL2: Mol* cannot draw")

    asyncio.run(scenario())


def test_project_files(tmp_path):
    async def scenario():
        async with sidecar() as s:
            form = aiohttp.FormData()
            form.add_field("file", b"ATOM", filename="a.pdb")
            r = await s.http.put(s.origin.make_url("/v3/file/app/out/a.pdb"), data=form)
            assert r.status == 200
            assert (tmp_path / "files/app/out/a.pdb").read_bytes() == b"ATOM"
            r = await s.http.get(s.origin.make_url("/v3/file/app/out/a.pdb"))
            assert await r.read() == b"ATOM"

    asyncio.run(scenario())
    assert server.project_file("other/a.pdb") is None  # not this trial's project: the backend's
    with pytest.raises(web.HTTPForbidden):
        server.project_file("app/../../secret")


def test_local_cookie():
    h = 'access_token="Bearer x"; Domain=dev.example.org; HttpOnly; Path=/v3; Secure; SameSite=strict'
    assert server.local_cookie(h) == 'access_token="Bearer x"; HttpOnly; Path=/v3; SameSite=strict'
