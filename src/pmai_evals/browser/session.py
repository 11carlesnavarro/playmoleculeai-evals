"""PMBrowser: async context-managed Playwright wrapper.

One ``PMBrowser`` per (run, model). Each ``new_chat`` runs in its own
fresh ``BrowserContext`` so a per-case auth-token rotation (the project
download refreshes the token) cannot leak into and wedge later cases.
Auth is loaded per context from the storage state file produced by
``pmai-evals setup-auth``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Any, Final

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

_AUTH_COOKIES: Final[tuple[str, ...]] = ("access_token", "refresh_token", "csrf_token")


async def _type_into_label(page: Any, label: str, value: str) -> None:
    """Focus a labelled input then type per-key, surviving React re-mounts.

    ``Locator.fill`` resolves the element once; if the form re-renders during
    hydration the handle goes stale. Click locks focus on the live element,
    then per-keystroke typing routes through the focused node.
    """
    field = page.get_by_label(label)
    await field.wait_for(state="visible", timeout=15_000)
    await field.click()
    await page.keyboard.type(value)


class PMBrowser:
    """Async context manager bound to one playmoleculeAI frontend URL."""

    def __init__(self, settings: Settings, *, storage_state: Path | None = None):
        self._settings = settings
        self._storage_state = storage_state or settings.auth_state_path
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None

    async def __aenter__(self) -> PMBrowser:
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        try:
            self._browser = await self._playwright.chromium.launch(
                headless=self._settings.pmai_evals_headless,
            )
        except Exception as exc:
            raise BrowserError(f"failed to launch chromium: {exc}") from exc

        self._context = await self._make_context()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        for label, target in (("context", self._context), ("browser", self._browser)):
            if target is None:
                continue
            try:
                await target.close()
            except Exception as e:
                logger.warning("%s close failed: %s", label, e)
        if self._playwright is not None:
            await self._playwright.stop()

    # ---- public API -----------------------------------------------------

    async def ensure_authenticated(self) -> None:
        """Confirm the saved storage state still grants access."""
        await self._wait_for_auth_cookies(timeout_s=2.0)

    async def new_chat(self, *, model: str) -> ChatSession:
        """Open a fresh, isolated context+page and prepare a new chat.

        Each case gets its own ``BrowserContext`` reloaded from the saved
        storage state. The prior context is closed first, so an auth-token
        rotation performed during a case (e.g. the project-zip download)
        stays contained and cannot wedge the next case's agent session.
        """
        from pmai_evals.browser.chat import ChatSession

        if self._browser is None:
            raise BrowserError("PMBrowser not entered")

        if self._context is not None:
            try:
                await self._context.close()
            except Exception as exc:
                logger.warning("previous context close failed: %s", exc)
        self._context = await self._make_context()

        page = await self._context.new_page()
        try:
            await page.goto(self._settings.pm_frontend_url)
        except Exception as exc:
            await page.close()
            raise BrowserError(f"navigation failed: {exc}") from exc

        chat = ChatSession(page=page, model=model, settings=self._settings)
        await chat.prepare()
        # Contexts are ephemeral, so the PMAI_MODEL cookie never carries
        # over; always re-pick the model.
        await chat.select_model()
        return chat

    async def login_and_save(self) -> None:
        """Drive the email/password form, then persist the resulting cookies."""
        if self._context is None:
            raise BrowserError("PMBrowser not entered")
        if not (self._settings.pm_email and self._settings.pm_password):
            raise AuthError("PM_EMAIL / PM_PASSWORD are unset")

        page = await self._context.new_page()
        try:
            await page.goto(f"{self._settings.pm_frontend_url}/login")
            await _type_into_label(page, EMAIL_LABEL, self._settings.pm_email)
            await _type_into_label(page, PASSWORD_LABEL, self._settings.pm_password)
            await page.get_by_role(SUBMIT_BUTTON[0], name=SUBMIT_BUTTON[1]).click()
            try:
                await page.get_by_role(
                    ACCOUNT_BUTTON[0], name=ACCOUNT_BUTTON[1]
                ).wait_for(timeout=30_000)
            except Exception as exc:
                raise AuthError("login did not reach the dashboard") from exc

            await self._wait_for_auth_cookies(timeout_s=10.0)
            self._storage_state.parent.mkdir(parents=True, exist_ok=True)
            await self._context.storage_state(path=str(self._storage_state))
            logger.info("storage state saved to %s", self._storage_state)
        finally:
            await page.close()

    # ---- internals ------------------------------------------------------

    async def _wait_for_auth_cookies(self, timeout_s: float) -> None:
        """Poll until all auth cookies are present, or raise.

        Backend sets ``access_token`` / ``refresh_token`` / ``csrf_token``
        asynchronously after login, so a UI-only probe can race past a
        half-finished flow. Cookies are the authoritative signal.
        """
        if self._context is None:
            raise BrowserError("PMBrowser not entered")
        deadline = time.monotonic() + timeout_s
        missing: set[str] = set(_AUTH_COOKIES)
        while time.monotonic() < deadline:
            present = {c["name"] for c in await self._context.cookies()}
            missing = set(_AUTH_COOKIES) - present
            if not missing:
                return
            await asyncio.sleep(0.25)
        raise AuthError(
            f"auth cookies missing after {timeout_s:.0f}s: {sorted(missing)}. "
            "Run `pmai-evals setup-auth`."
        )

    async def _make_context(self) -> BrowserContext:
        """Build a fresh context from the saved storage state.

        Project selection is pinned via the ``PM_PROJECT`` cookie (the
        frontend reads it on mount); without it the storage state decides
        which project is active.
        """
        if self._browser is None:
            raise BrowserError("PMBrowser not entered")
        kwargs: dict[str, object] = {}
        if self._storage_state.exists():
            kwargs["storage_state"] = str(self._storage_state)
        else:
            logger.warning(
                "no storage_state at %s; you'll need an interactive login flow",
                self._storage_state,
            )
        context = await self._browser.new_context(**kwargs)
        context.set_default_navigation_timeout(
            self._settings.pmai_evals_browser_navigation_timeout_s * 1000
        )
        await context.add_cookies([{
            "name": "PM_PROJECT",
            "value": self._settings.pm_project,
            "url": self._settings.pm_frontend_url,
        }])
        logger.info("pinned PM_PROJECT=%s", self._settings.pm_project)
        return context
