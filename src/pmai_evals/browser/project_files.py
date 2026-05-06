"""Drive the pmview File Browser panel to manage project files.

Uploads go through the frontend's hidden ``<input type=file>`` (the same
path the chonky toolbar drives). The chonky grid is virtualized, so we
confirm completion by polling the backend listing endpoint instead of
scraping visible names.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pmai_evals.browser import locators
from pmai_evals.errors import BrowserError

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


async def authed_fetch(
    page: Page,
    frontend_url: str,
    url: str,
    *,
    method: str = "GET",
    **kwargs: Any,
) -> Any:
    """Fetch with auto-refresh on 401, mirroring pmview's auth flow.

    Long-running cases outlive the access-token TTL. On 401 we POST to
    ``/v3/auth/refresh-token`` (cookies carry the refresh token) and replay
    the original request once with the rotated CSRF.
    """
    headers = dict(kwargs.pop("headers", None) or {})
    headers[_CSRF_HEADER] = await _read_csrf_token(page, frontend_url)
    resp = await page.request.fetch(url, method=method, headers=headers, **kwargs)
    if resp.status != 401:
        return resp
    refresh = await page.request.fetch(
        f"{frontend_url}/v3/auth/refresh-token",
        method="POST",
        headers={_CSRF_HEADER: headers[_CSRF_HEADER]},
    )
    if not refresh.ok:
        return resp
    headers[_CSRF_HEADER] = await _read_csrf_token(page, frontend_url)
    return await page.request.fetch(url, method=method, headers=headers, **kwargs)


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
    """Upload ``local_paths`` to the project root via the chonky upload input.

    Polls the backend listing until every basename is visible (the chonky
    grid is virtualized and unreliable as a completion signal).
    """
    if not local_paths:
        return
    expected = {p.name for p in local_paths}

    await _open_file_browser(page)
    try:
        logger.info("uploading %d files to project %s", len(local_paths), project)
        try:
            await page.locator(locators.PROJECT_UPLOAD_INPUT).first.set_input_files(
                [str(p) for p in local_paths]
            )
        except Exception as exc:
            raise BrowserError(f"set_input_files failed: {exc}") from exc

        deadline = time.monotonic() + timeout_s
        present: set[str] = set()
        while time.monotonic() < deadline:
            entries = await _list_project_entries(page, project, frontend_url)
            present = {e["name"] for e in entries}
            if expected.issubset(present):
                logger.info("uploaded %d files to project %s", len(expected), project)
                return
            await asyncio.sleep(1.0)
        missing = expected - present
        raise BrowserError(
            f"only {len(present & expected)}/{len(expected)} expected files "
            f"appeared in {project} within {timeout_s:.0f}s; "
            f"missing first 5: {sorted(missing)[:5]}"
        )
    finally:
        await _close_file_browser(page)
