"""Unit tests for ``PMBrowser._authed_fetch`` token-refresh path."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from pmai_evals.browser.session import PMBrowser
from pmai_evals.config import Settings
from pmai_evals.errors import AuthError, BrowserError


@dataclass
class _FakeResponse:
    status: int

    @property
    def ok(self) -> bool:
        return self.status < 400


@dataclass
class _FakeContext:
    """Records each fetch call and replays a queued list of responses."""

    responses: list[_FakeResponse]
    calls: list[dict[str, Any]] = field(default_factory=list)

    @property
    def request(self) -> _FakeContext:
        return self

    async def fetch(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append({"url": url, **kwargs})
        return self.responses.pop(0)


def _stub_browser(
    *responses: _FakeResponse,
    tokens: tuple[str, ...] = ("csrf-original", "csrf-rotated"),
) -> PMBrowser:
    browser = PMBrowser(Settings(), project="test-project")
    browser._context = _FakeContext(list(responses))  # type: ignore[assignment]
    queue = iter(tokens)

    async def fake_csrf() -> str:
        return next(queue, tokens[-1])

    async def fake_refresh() -> None:
        return None

    browser._read_csrf_token = fake_csrf  # type: ignore[method-assign]
    browser._refresh_access_token = fake_refresh  # type: ignore[method-assign]
    return browser


@pytest.mark.asyncio
async def test_authed_fetch_succeeds_first_try() -> None:
    browser = _stub_browser(_FakeResponse(200))
    resp = await browser._authed_fetch("https://x/foo")
    assert resp.status == 200
    ctx = browser._context  # type: ignore[union-attr]
    assert ctx.calls[0]["headers"] == {"X-CSRF-Token": "csrf-original"}


@pytest.mark.asyncio
async def test_authed_fetch_retries_with_rotated_csrf_after_401() -> None:
    browser = _stub_browser(_FakeResponse(401), _FakeResponse(200))
    resp = await browser._authed_fetch("https://x/foo", method="DELETE")
    assert resp.status == 200

    ctx = browser._context  # type: ignore[union-attr]
    assert [c["url"] for c in ctx.calls] == ["https://x/foo", "https://x/foo"]
    assert ctx.calls[0]["headers"] == {"X-CSRF-Token": "csrf-original"}
    assert ctx.calls[1]["headers"] == {"X-CSRF-Token": "csrf-rotated"}
    assert ctx.calls[1]["method"] == "DELETE"


@pytest.mark.asyncio
async def test_authed_fetch_requires_csrf_cookie() -> None:
    browser = _stub_browser(tokens=("",))
    with pytest.raises(AuthError):
        await browser._authed_fetch("https://x/foo")


@pytest.mark.asyncio
async def test_authed_fetch_requires_context() -> None:
    browser = PMBrowser(Settings(), project="x")
    with pytest.raises(BrowserError):
        await browser._authed_fetch("https://x/foo")
