"""Manage project files: list/delete via the backend API, upload via the UI.

List and delete go through the agent backend's ``/v3/file*`` endpoints
wrapped by :func:`authed_fetch` (auth refresh + transient retry). Uploads
go through the frontend's hidden ``<input type=file>``, observing the
resulting PUT responses so silent backend failures surface immediately
and the call retries instead of timing out on a missing-files poll.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote

from pmai_evals.browser import locators
from pmai_evals.errors import BrowserError, TerminalUploadError

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)

_CSRF_HEADER = "X-CSRF-Token"
_CSRF_COOKIE = "csrf_token"


async def _open_file_browser(page: Page, *, timeout_s: float = 60.0) -> None:
    timeout_ms = int(timeout_s * 1000)
    try:
        await page.locator(locators.FILE_BROWSER_ICON).first.click(timeout=timeout_ms)
        await page.locator(locators.CHONKY_ROOT).first.wait_for(
            state="visible", timeout=timeout_ms
        )
    except Exception as exc:
        raise BrowserError(f"could not open File Browser panel: {exc}") from exc
    logger.info("File Browser panel open")


async def _close_file_browser(page: Page, *, timeout_s: float = 10.0) -> None:
    chonky = page.locator(locators.CHONKY_ROOT).first
    if not await chonky.is_visible():
        return
    timeout_ms = int(timeout_s * 1000)
    try:
        await page.locator(locators.FILE_BROWSER_ICON).first.click(timeout=timeout_ms)
        await chonky.wait_for(state="hidden", timeout=timeout_ms)
    except Exception as exc:
        raise BrowserError(f"could not close File Browser panel: {exc}") from exc


async def _read_csrf_token(page: Page, frontend_url: str) -> str:
    for cookie in await page.context.cookies(frontend_url):
        if cookie.get("name") == _CSRF_COOKIE:
            return cookie.get("value") or ""
    return ""


async def _safe_body(resp: Any, limit: int = 200) -> str:
    try:
        return (await resp.text())[:limit]
    except Exception:
        return ""


_TRANSIENT_STATUSES = frozenset({401, 408, 425, 429, 500, 502, 503, 504})
# Uploads go through the browser's auth path, so 401/403 can clear after a
# retry plus token rotation; we let the retry loop try once before giving up.
_RETRIABLE_UPLOAD_STATUSES = frozenset({401, 403, 408, 425, 429, 500, 502, 503, 504})

_DEFAULT_RETRIES = 2
_DEFAULT_BACKOFF_S = 0.75


async def _refresh_access_token(page: Page, frontend_url: str, csrf: str) -> bool:
    """POST ``/v3/auth/refresh-token``; return whether the session rotated."""
    resp = await page.request.fetch(
        f"{frontend_url}/v3/auth/refresh-token",
        method="POST",
        headers={_CSRF_HEADER: csrf},
    )
    if not resp.ok:
        logger.warning("refresh-token failed: status=%d", resp.status)
    return resp.ok


async def authed_fetch(
    page: Page,
    frontend_url: str,
    url: str,
    *,
    method: str = "GET",
    **kwargs: Any,
) -> Any:
    """Authenticated request with one-shot refresh on 401 and bounded retry.

    Long-running cases outlive the access-token TTL: a 401 triggers a single
    POST to ``/v3/auth/refresh-token`` (cookies carry the refresh token) and
    a replay with the rotated CSRF. Transient failures (5xx, network
    exceptions, persistent 401) are then retried with exponential backoff
    before the last response is returned.
    """
    headers = dict(kwargs.pop("headers", None) or {})
    refresh_used = False
    delay = _DEFAULT_BACKOFF_S

    async def attempt() -> Any:
        headers[_CSRF_HEADER] = await _read_csrf_token(page, frontend_url)
        return await page.request.fetch(url, method=method, headers=headers, **kwargs)

    last_attempt = _DEFAULT_RETRIES
    for n in range(last_attempt + 1):
        try:
            resp = await attempt()
            if resp.status == 401 and not refresh_used:
                refresh_used = True
                if await _refresh_access_token(page, frontend_url, headers[_CSRF_HEADER]):
                    resp = await attempt()
            if resp.status not in _TRANSIENT_STATUSES or n == last_attempt:
                return resp
            logger.warning(
                "authed_fetch %s %s status=%d (attempt %d/%d); retry in %.2fs",
                method, url, resp.status, n + 1, last_attempt + 1, delay,
            )
        except Exception as exc:
            if n == last_attempt:
                raise
            logger.warning(
                "authed_fetch %s %s raised %s (attempt %d/%d); retry in %.2fs",
                method, url, exc, n + 1, last_attempt + 1, delay,
            )
        await asyncio.sleep(delay)
        delay *= 2

    raise BrowserError(f"{method} {url}: retry loop exhausted")


async def _list_project_entries(
    page: Page, project: str, frontend_url: str
) -> list[dict[str, Any]]:
    """Immediate children of ``<project>/`` from the backend, or [] if 404."""
    url = f"{frontend_url}/v3/files?recursive=false&prefix={project}/"
    try:
        resp = await authed_fetch(page, frontend_url, url, method="GET")
    except Exception as exc:
        raise BrowserError(f"GET {url} failed: {exc}") from exc
    if resp.status == 404:
        return []
    if not resp.ok:
        raise BrowserError(
            f"list project files failed: status={resp.status} body={await _safe_body(resp)!r}"
        )
    listing = await resp.json()
    if not isinstance(listing, dict):
        raise BrowserError(
            f"list project files: unexpected shape {type(listing).__name__}"
        )
    return [e for e in listing.values() if isinstance(e, dict) and "name" in e]


async def clear_project(page: Page, *, project: str, frontend_url: str) -> int:
    """Delete every file/folder under ``<project>/``. Returns count deleted."""
    entries = await _list_project_entries(page, project, frontend_url)
    if not entries:
        logger.info("clear_project: %s already empty", project)
        return 0

    deleted = 0
    for entry in entries:
        suffix = "/" if entry.get("isDir") else ""
        url = f"{frontend_url}/v3/file/{project}/{entry['name']}{suffix}"
        try:
            r = await authed_fetch(page, frontend_url, url, method="DELETE")
        except Exception as exc:
            logger.warning("clear_project: DELETE %s raised: %s", url, exc)
            continue
        if r.ok:
            deleted += 1
        else:
            logger.warning(
                "clear_project: DELETE %s failed status=%s body=%s",
                url, r.status, await _safe_body(r, 120),
            )
    logger.info(
        "clear_project: deleted %d/%d entries from project %s",
        deleted, len(entries), project,
    )
    return deleted


async def upload_to_project(
    page: Page,
    local_paths: list[Path],
    *,
    project: str,
    frontend_url: str,
    timeout_s: float = 600.0,
) -> None:
    """Upload ``local_paths`` via the frontend's hidden file input.

    Streaming and auth come for free from the browser. Each file's
    ``PUT /v3/file/...`` response is observed so silent backend failures
    raise immediately; the whole upload retries with backoff.
    """
    if not local_paths:
        return
    last_attempt = _DEFAULT_RETRIES
    for attempt in range(last_attempt + 1):
        try:
            await _upload_once(
                page, local_paths,
                project=project, frontend_url=frontend_url, timeout_s=timeout_s,
            )
            return
        except TerminalUploadError:
            raise
        except BrowserError as exc:
            if attempt == last_attempt:
                raise
            wait = 2.0 * (attempt + 1)
            logger.warning(
                "upload to %s failed (attempt %d/%d): %s; retry in %.1fs",
                project, attempt + 1, last_attempt + 1, exc, wait,
            )
            await asyncio.sleep(wait)
            # The frontend's upload path doesn't always refresh on its own;
            # rotate tokens server-side so the next attempt sees fresh auth.
            await _refresh_access_token(
                page, frontend_url, await _read_csrf_token(page, frontend_url)
            )


async def _upload_once(
    page: Page, local_paths: list[Path],
    *, project: str, frontend_url: str, timeout_s: float,
) -> None:
    expected = {p.name for p in local_paths}
    seen: dict[str, int] = {}
    done = asyncio.Event()

    def on_response(resp: Any) -> None:
        if resp.request.method != "PUT" or "/v3/file/" not in resp.url:
            return
        name = unquote(resp.url.rsplit("/", 1)[-1])
        if name in expected:
            seen[name] = resp.status
            if set(seen) >= expected:
                done.set()

    try:
        page.on("response", on_response)
        await _open_file_browser(page)
        logger.info("uploading %d files to project %s", len(local_paths), project)
        for p in local_paths:
            logger.info("  -> %s (%.1f MB)", p.name, p.stat().st_size / 1e6)
        try:
            await page.locator(locators.PROJECT_UPLOAD_INPUT).first.set_input_files(
                [str(p) for p in local_paths]
            )
        except Exception as exc:
            raise BrowserError(f"set_input_files failed: {exc}") from exc

        try:
            await asyncio.wait_for(done.wait(), timeout=timeout_s)
        except TimeoutError:
            raise BrowserError(
                f"upload timed out after {timeout_s:.0f}s; "
                f"no PUT response for: {sorted(expected - set(seen))[:5]}"
            ) from None

        if bad := {n: s for n, s in seen.items() if s >= 400}:
            terminal = any(s not in _RETRIABLE_UPLOAD_STATUSES for s in bad.values())
            cls = TerminalUploadError if terminal else BrowserError
            raise cls(f"upload PUTs failed: {bad}")

        logger.info("uploaded %d files to project %s", len(expected), project)
    finally:
        page.remove_listener("response", on_response)
        await _close_file_browser(page)
