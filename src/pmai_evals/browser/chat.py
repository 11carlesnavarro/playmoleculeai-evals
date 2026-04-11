"""ChatSession — one prompt, one rollout, one set of artifacts.

Single-use. After ``wait_for_completion``, fetch the artifacts you need
(screenshot, viewer state, final answer, history), then close. Sending a
second prompt through the same session is forbidden — open a fresh
``ChatSession`` instead.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pmai_evals.browser import locators
from pmai_evals.browser.fixtures import upload_fixtures_for_chat
from pmai_evals.browser.observers import (
    PYODIDE_READY,
    SCREENSHOT_DATA_URI,
    VIEWER_STATE_JSON,
)
from pmai_evals.config import Settings
from pmai_evals.errors import BrowserError, ChatTimeoutError, TraceParseError

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)


class CompletionStatus(StrEnum):
    completed = "completed"
    failed = "failed"
    timed_out = "timed_out"


class ChatSession:
    """One Page, one chat. Single-use."""

    def __init__(
        self,
        *,
        page: Page,
        model: str,
        project: str,
        settings: Settings,
    ) -> None:
        self._page = page
        self._model = model
        self._project = project
        self._settings = settings
        self._chat_id: str = ""
        self._closed = False

    # ---- properties -----------------------------------------------------

    @property
    def chat_id(self) -> str:
        return self._chat_id

    @property
    def page(self) -> Page:
        return self._page

    # ---- lifecycle ------------------------------------------------------

    async def prepare(self) -> None:
        """Wait for the page's Pyodide worker and Molstar viewer to be live.

        We don't fail hard if Pyodide isn't ready inside the probe window —
        some pages defer the worker until first use. The runner observes
        viewer state lazily and treats absence as a recoverable warning.
        """

        try:
            await self._page.wait_for_load_state("domcontentloaded")
        except Exception as exc:
            raise BrowserError(f"page failed to load: {exc}") from exc

        # Best-effort: poll for Pyodide for ~10s, but don't crash if absent.
        for _ in range(20):
            try:
                ready = await self._page.evaluate(PYODIDE_READY)
                if ready:
                    break
            except Exception:
                pass
            await asyncio.sleep(0.5)


    async def upload_fixtures(self, fixtures: Sequence[Path]) -> None:
        await upload_fixtures_for_chat(self._page, list(fixtures), self._settings, self._project)

    async def send_prompt(self, prompt: str) -> None:
        """Fill the prompt box, submit, and capture the chat_id.

        The ``x-chat-id`` response header on ``POST /v3/agent/chat/rollout``
        is the server's authoritative handle for the chat being created.
        We mirror what the frontend's ``sendMessage.ts`` does: wrap the
        Enter keystroke in ``expect_response`` and read the header the
        moment it arrives.
        """

        try:
            box = self._page.get_by_role(
                locators.PROMPT_INPUT[0], name=locators.PROMPT_INPUT[1]
            )
            await box.fill(prompt)
            async with self._page.expect_response(
                lambda r: "rollout" in r.url, timeout=30_000
            ) as info:
                await box.press("Enter")
            resp = await info.value
        except Exception as exc:
            raise BrowserError(f"could not submit prompt: {exc}") from exc

        chat_id = resp.headers.get("x-chat-id", "")
        if not chat_id:
            raise BrowserError(
                f"rollout response had no x-chat-id header; status={resp.status}"
            )
        self._chat_id = chat_id

    async def wait_for_completion(self, *, timeout_s: int) -> CompletionStatus:
        """Block until the run finishes or times out.

        Primary signal: the ``Regenerate`` button becomes enabled. The
        playmolecule frontend re-enables it once the model has finished
        streaming and any pmview tool calls have settled.
        """

        from playwright.async_api import TimeoutError as PWTimeout

        regenerate = self._page.get_by_role(
            locators.REGENERATE_BUTTON[0], name=locators.REGENERATE_BUTTON[1]
        )
        try:
            await regenerate.wait_for(timeout=timeout_s * 1000)
            # Wait until it's actually enabled, not just present.
            for _ in range(timeout_s * 2):
                if await regenerate.is_enabled():
                    break
                await asyncio.sleep(0.5)
            else:
                raise ChatTimeoutError(
                    f"Regenerate button never enabled within {timeout_s}s"
                )
        except PWTimeout as exc:
            raise ChatTimeoutError(
                f"Regenerate button never appeared within {timeout_s}s"
            ) from exc

        return CompletionStatus.completed

    # ---- observers ------------------------------------------------------

    async def fetch_history(self) -> list[dict[str, Any]]:
        """Return the full chat history from ``GET /v3/agent/chat/{id}``.

        Call after ``send_prompt`` (so ``chat_id`` is set) and before
        ``delete_chat``.
        """

        if not self._chat_id:
            raise BrowserError("chat_id is empty; call send_prompt first")
        resp = await self._chat_api_request("GET")
        if not resp.ok:
            body = ""
            try:
                body = (await resp.text())[:200]
            except Exception:
                pass
            raise BrowserError(
                f"chat history fetch failed: status={resp.status} body={body!r}"
            )
        try:
            data = await resp.json()
        except Exception as exc:
            raise TraceParseError(f"chat history body was not JSON: {exc}") from exc
        if not isinstance(data, list):
            raise TraceParseError(
                f"chat history response shape unexpected: got {type(data).__name__}"
            )
        return data

    async def _chat_api_request(self, method: str) -> Any:
        """Call ``/v3/agent/chat/{chat_uid}`` with the required CSRF header.

        The backend uses a double-submit cookie CSRF scheme: the client
        must echo the ``csrf_token`` cookie value in an ``X-CSRF-Token``
        header. ``page.request`` sends cookies but not derived headers,
        so we add it explicitly.
        """
        url = f"{self._settings.pm_frontend_url}/v3/agent/chat/{self._chat_id}"
        headers = {"X-CSRF-Token": await self._read_csrf_token()}
        try:
            return await self._page.request.fetch(url, method=method, headers=headers)
        except Exception as exc:
            raise BrowserError(f"{method} {url} failed: {exc}") from exc

    async def _read_csrf_token(self) -> str:
        cookies = await self._page.context.cookies(self._settings.pm_frontend_url)
        for cookie in cookies:
            if cookie.get("name") == "csrf_token":
                return cookie.get("value") or ""
        return ""

    async def get_viewer_state(self) -> dict[str, Any]:
        """Return the in-page systems_tree as a Python dict."""
        try:
            raw = await self._page.evaluate(VIEWER_STATE_JSON)
        except Exception as exc:
            raise BrowserError(f"viewer state eval failed: {exc}") from exc
        if raw is None:
            return {}
        if isinstance(raw, str):
            try:
                import json

                return json.loads(raw)
            except ValueError:
                return {"_raw": raw}
        if isinstance(raw, dict):
            return raw
        return {"_raw": str(raw)}

    async def save_screenshot(self, path: Path) -> None:
        """Save a Molstar viewport screenshot to ``path``.

        Falls back to a full-page screenshot if Molstar's helper isn't
        available — better than nothing for the LLM judge.
        """

        try:
            data_uri = await self._page.evaluate(SCREENSHOT_DATA_URI)
        except Exception as exc:
            raise BrowserError(f"screenshot eval failed: {exc}") from exc

        if isinstance(data_uri, str) and data_uri.startswith("data:image"):
            import base64

            try:
                _, b64 = data_uri.split(",", 1)
            except ValueError as exc:
                raise BrowserError("malformed data URI from Molstar") from exc
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(base64.b64decode(b64))
            return

        # Fallback: full-page screenshot via Playwright.
        path.parent.mkdir(parents=True, exist_ok=True)
        await self._page.screenshot(path=str(path), full_page=True)

    async def get_final_answer(self) -> str:
        """Pull the last assistant message from the DOM as plain text.

        The trace DB is the canonical source — this is a courtesy fallback
        for when the trace lookup hasn't happened yet (e.g. for live
        debugging).
        """

        try:
            handles = await self._page.locator("[data-role='assistant'], .assistant-message").all()
            if not handles:
                return ""
            return (await handles[-1].inner_text()) or ""
        except Exception as exc:
            logger.debug("final answer DOM scrape failed: %s", exc)
            return ""

    # ---- teardown -------------------------------------------------------

    async def delete_chat(self) -> None:
        """Soft-delete this chat via ``DELETE /v3/agent/chat/{id}``. Best-effort."""
        if not self._chat_id:
            return
        try:
            resp = await self._chat_api_request("DELETE")
            if not resp.ok:
                logger.debug("delete_chat %s returned %s", self._chat_id, resp.status)
        except Exception as exc:
            logger.debug("delete_chat failed: %s", exc)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._page.close()
        except Exception as exc:
            logger.debug("page close failed: %s", exc)
