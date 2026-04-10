"""PMBrowser — async context-managed Playwright wrapper.

One ``PMBrowser`` per (run, model). Owns one ``BrowserContext`` and reuses
it across cases for that model. Auth is amortized via the storage state
file produced by ``pmai-evals setup-auth``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING

from pmai_evals.browser.locators import (
    ACCOUNT_BUTTON,
    EMAIL_LABEL,
    PASSWORD_LABEL,
    SUBMIT_BUTTON,
)
from pmai_evals.config import Settings
from pmai_evals.errors import AuthError, BrowserError

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Playwright

    from pmai_evals.browser.chat import ChatSession

logger = logging.getLogger(__name__)


class PMBrowser:
    """Async context manager bound to one playmoleculeAI frontend URL."""

    def __init__(self, settings: Settings, *, storage_state: Path | None = None):
        self._settings = settings
        self._storage_state = storage_state or settings.auth_state_path
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None

    # ---- context manager ------------------------------------------------

    async def __aenter__(self) -> PMBrowser:
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        try:
            self._browser = await self._playwright.chromium.launch(
                headless=self._settings.pmai_evals_headless,
            )
        except Exception as exc:
            raise BrowserError(f"failed to launch chromium: {exc}") from exc

        context_kwargs: dict[str, object] = {}
        if self._storage_state.exists():
            context_kwargs["storage_state"] = str(self._storage_state)
        else:
            logger.warning(
                "no storage_state at %s; you'll need an interactive login flow",
                self._storage_state,
            )
        self._context = await self._browser.new_context(**context_kwargs)
        self._context.set_default_navigation_timeout(
            self._settings.pmai_evals_browser_navigation_timeout_s * 1000
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._context is not None:
            try:
                await self._context.close()
            except Exception as e:
                logger.warning("context close failed: %s", e)
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception as e:
                logger.warning("browser close failed: %s", e)
        if self._playwright is not None:
            await self._playwright.stop()

    # ---- public API -----------------------------------------------------

    async def ensure_authenticated(self) -> None:
        """Confirm the saved storage state still grants access.

        Performs a cheap probe: open the frontend, look for the account
        button. If not present, raise — the user is expected to re-run
        ``pmai-evals setup-auth``.
        """

        if self._context is None:
            raise BrowserError("PMBrowser not entered")
        page = await self._context.new_page()
        try:
            await page.goto(self._settings.pm_frontend_url)
            try:
                await page.get_by_role(
                    ACCOUNT_BUTTON[0], name=ACCOUNT_BUTTON[1]
                ).wait_for(timeout=15_000)
            except Exception as exc:
                raise AuthError(
                    "no Account button visible; storage state is missing or expired. "
                    "Run `pmai-evals setup-auth`."
                ) from exc
        finally:
            await page.close()

    async def new_chat(self, *, model: str, project: str) -> ChatSession:
        """Open a fresh page and prepare a new chat for one rollout."""
        from pmai_evals.browser.chat import ChatSession

        if self._context is None:
            raise BrowserError("PMBrowser not entered")

        page = await self._context.new_page()
        try:
            await page.goto(self._settings.pm_frontend_url)
        except Exception as exc:
            await page.close()
            raise BrowserError(f"navigation failed: {exc}") from exc

        chat = ChatSession(page=page, model=model, project=project, settings=self._settings)
        await chat.prepare()
        return chat

    # ---- one-shot login (used by setup-auth) ----------------------------

    async def login_and_save(self) -> None:
        """Run the interactive login flow and persist storage state.

        Uses the email/password from settings. Called only by the
        ``setup-auth`` CLI command.
        """

        if self._context is None:
            raise BrowserError("PMBrowser not entered")
        if not (self._settings.pm_email and self._settings.pm_password):
            raise AuthError("PM_EMAIL and PM_PASSWORD must be set in .env to log in")

        page = await self._context.new_page()
        try:
            await page.goto(f"{self._settings.pm_frontend_url}/login")
            await page.get_by_label(EMAIL_LABEL).fill(self._settings.pm_email)
            await page.get_by_label(PASSWORD_LABEL).fill(self._settings.pm_password)
            await page.get_by_role(SUBMIT_BUTTON[0], name=SUBMIT_BUTTON[1]).click()

            try:
                await page.get_by_role(
                    ACCOUNT_BUTTON[0], name=ACCOUNT_BUTTON[1]
                ).wait_for(timeout=30_000)
            except Exception as exc:
                raise AuthError("login did not reach the dashboard") from exc

            self._storage_state.parent.mkdir(parents=True, exist_ok=True)
            await self._context.storage_state(path=str(self._storage_state))
            logger.info("storage state saved to %s", self._storage_state)
        finally:
            await page.close()
