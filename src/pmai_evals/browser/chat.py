"""ChatSession: one prompt, one rollout, one set of artifacts.

Single-use. After ``wait_for_completion``, fetch the artifacts you need
and ``close()``. Sending a second prompt is forbidden, open a fresh
``ChatSession`` instead.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pmai_evals.browser import locators
from pmai_evals.browser.observers import (
    PYODIDE_READY,
    SCREENSHOT_DATA_URI,
    VIEWER_SELECTION_JSON,
    VIEWER_STATE_JSON,
)
from pmai_evals.browser.project_files import authed_fetch
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

    def __init__(self, *, page: Page, model: str, settings: Settings) -> None:
        self._page = page
        self._model = model
        self._settings = settings
        self._chat_id: str = ""
        self._closed = False

    @property
    def chat_id(self) -> str:
        return self._chat_id

    @property
    def page(self) -> Page:
        return self._page

    # ---- lifecycle ------------------------------------------------------

    async def prepare(self) -> None:
        """Wait for the page's Pyodide worker and Molstar viewer to be live.

        Best-effort: poll for ~10s but don't crash if Pyodide isn't ready.
        Some pages defer the worker until first use; the runner handles
        absence as a recoverable warning.
        """
        try:
            await self._page.wait_for_load_state("domcontentloaded")
        except Exception as exc:
            raise BrowserError(f"page failed to load: {exc}") from exc

        for _ in range(20):
            try:
                if await self._page.evaluate(PYODIDE_READY):
                    return
            except Exception:
                pass
            await asyncio.sleep(0.5)

    async def select_model(self) -> None:
        """Pick ``self._model`` via the Settings dialog."""
        page = self._page
        dialog = page.get_by_role(
            locators.SETTINGS_DIALOG[0], name=locators.SETTINGS_DIALOG[1]
        )
        try:
            await page.get_by_label(locators.SETTINGS_BUTTON_LABEL, exact=True).click()
            await dialog.wait_for()
            await page.get_by_role(
                locators.MODEL_SELECT[0], name=locators.MODEL_SELECT[1]
            ).click()
            target = page.get_by_role("option", name=self._model, exact=True)
            if await target.count() == 0:
                available = [
                    t.strip() for t in await page.get_by_role("option").all_inner_texts()
                ]
                raise BrowserError(
                    f"model {self._model!r} not offered by pmview; available: {available}"
                )
            await target.click()
            await page.keyboard.press("Escape")
            await dialog.wait_for(state="hidden")
        except BrowserError:
            raise
        except Exception as exc:
            raise BrowserError(f"model selection failed: {exc}") from exc

    async def send_prompt(self, prompt: str) -> None:
        """Fill the prompt box, submit, and capture the chat_id.

        The ``x-chat-id`` response header on ``POST /v3/agent/chat/rollout``
        is the server's authoritative handle for the chat.
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

        body = resp.request.post_data_json
        if not isinstance(body, dict):
            raise BrowserError(f"rollout request body unreadable: {body!r}")
        sent = body.get("model")
        if sent != self._model:
            raise BrowserError(
                f"rollout used model {sent!r}, expected {self._model!r}"
            )

    async def wait_for_completion(self, *, timeout_s: int | None) -> CompletionStatus:
        """Block until the run finishes or times out.

        Primary signal: the ``Regenerate`` button becomes enabled. The
        playmolecule frontend re-enables it once the model has finished
        streaming and any pmview tool calls have settled.
        """
        from playwright.async_api import TimeoutError as PWTimeout

        regenerate = self._page.get_by_role(
            locators.REGENERATE_BUTTON[0], name=locators.REGENERATE_BUTTON[1]
        )
        wait_ms = 0 if timeout_s is None else timeout_s * 1000
        try:
            await regenerate.wait_for(timeout=wait_ms)
            if timeout_s is None:
                while not await regenerate.is_enabled():
                    await asyncio.sleep(0.5)
            else:
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
        """Return the full chat history from ``GET /v3/agent/chat/{id}``."""
        if not self._chat_id:
            raise BrowserError("chat_id is empty; call send_prompt first")

        url = f"{self._settings.pm_frontend_url}/v3/agent/chat/{self._chat_id}?full=true"
        try:
            resp = await authed_fetch(
                self._page, self._settings.pm_frontend_url, url, method="GET"
            )
        except Exception as exc:
            raise BrowserError(f"GET {url} failed: {exc}") from exc

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

    async def get_viewer_state(self) -> dict[str, Any]:
        return await self._eval_pyodide_json(VIEWER_STATE_JSON, "viewer state")

    async def get_viewer_selection(self) -> dict[str, Any]:
        """Return ``{moleculeID: "index ..."}`` (atomselect string), or {}."""
        return await self._eval_pyodide_json(VIEWER_SELECTION_JSON, "viewer selection")

    async def _eval_pyodide_json(self, observer: str, label: str) -> dict[str, Any]:
        try:
            raw = await self._page.evaluate(observer)
        except Exception as exc:
            raise BrowserError(f"{label} eval failed: {exc}") from exc
        if raw is None:
            return {}
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except ValueError:
                return {"_raw": raw}
        if isinstance(raw, dict):
            return raw
        return {"_raw": str(raw)}

    async def save_screenshot(self, path: Path) -> None:
        """Save a Molstar viewport screenshot, falling back to the full page."""
        try:
            data_uri = await self._page.evaluate(SCREENSHOT_DATA_URI)
        except Exception as exc:
            raise BrowserError(f"screenshot eval failed: {exc}") from exc

        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data_uri, str) and data_uri.startswith("data:image"):
            try:
                _, b64 = data_uri.split(",", 1)
            except ValueError as exc:
                raise BrowserError("malformed data URI from Molstar") from exc
            path.write_bytes(base64.b64decode(b64))
            return
        await self._page.screenshot(path=str(path), full_page=True)

    async def get_final_answer(self) -> str:
        """Pull the last assistant message from the DOM as plain text."""
        try:
            handles = await self._page.locator(
                "[data-role='assistant'], .assistant-message"
            ).all()
            if not handles:
                return ""
            return (await handles[-1].inner_text()) or ""
        except Exception as exc:
            logger.debug("final answer DOM scrape failed: %s", exc)
            return ""

    # ---- teardown -------------------------------------------------------

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._page.close()
        except Exception as exc:
            logger.debug("page close failed: %s", exc)
