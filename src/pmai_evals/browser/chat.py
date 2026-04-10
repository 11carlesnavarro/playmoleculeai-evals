"""ChatSession — one prompt, one rollout, one set of artifacts.

ChatSession is single-use. After ``wait_for_completion``, fetch the
artifacts you need (screenshot, viewer state, final answer), then close.
Sending a second prompt through the same session is forbidden — open a
fresh ``ChatSession`` instead. This keeps cross-case state leakage at zero.

Completion detection (spec §4.2) has three fallbacks, checked in order:
    1. ``Regenerate`` button enabled.
    2. (TODO) Trace status flips to "completed" in SQLite.
    3. Hard timeout.
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
    CHAT_ID_FROM_PAGE,
    PYODIDE_READY,
    SCREENSHOT_DATA_URI,
    VIEWER_STATE_JSON,
)
from pmai_evals.config import Settings
from pmai_evals.errors import BrowserError, ChatTimeoutError

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

        # Model picker. The exact UI affordance is open question §9.1; we
        # try a best-effort role-based selection here. If the picker isn't
        # present, log and continue — the agent will use whatever default
        # the frontend is wired to.
        try:
            picker = self._page.get_by_role(
                locators.MODEL_PICKER_BUTTON[0],
                name=locators.MODEL_PICKER_BUTTON[1],
            )
            if await picker.count() > 0:
                await picker.click()
                await self._page.get_by_role("option", name=self._model).click()
        except Exception as exc:
            logger.debug("model picker not used (%s)", exc)

    async def upload_fixtures(self, fixtures: Sequence[Path]) -> None:
        await upload_fixtures_for_chat(self._page, list(fixtures), self._settings, self._project)

    async def send_prompt(self, prompt: str) -> None:
        try:
            box = self._page.get_by_role(
                locators.PROMPT_INPUT[0], name=locators.PROMPT_INPUT[1]
            )
            await box.fill(prompt)
            await box.press("Enter")
        except Exception as exc:
            raise BrowserError(f"could not submit prompt: {exc}") from exc

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

        # Capture chat_id while we're here. The runner needs it to query
        # the trace DB.
        try:
            cid = await self._page.evaluate(CHAT_ID_FROM_PAGE)
            if isinstance(cid, str) and cid:
                self._chat_id = cid
        except Exception as exc:
            logger.debug("chat_id extraction failed: %s", exc)

        return CompletionStatus.completed

    # ---- observers ------------------------------------------------------

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
        """Open the history menu and delete this chat. Best-effort."""
        try:
            await self._page.get_by_role(
                locators.SHOW_HISTORY_BUTTON[0], name=locators.SHOW_HISTORY_BUTTON[1]
            ).click()
            menuitem = self._page.get_by_role("menuitem").first
            await menuitem.locator(".MuiIconButton-edgeEnd").click()
            await self._page.get_by_role(
                locators.DELETE_MENUITEM[0], name=locators.DELETE_MENUITEM[1]
            ).click()
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
