"""Drive the pmview File Browser panel to move project files in and out.

Uploads go through the frontend's hidden ``<input type=file>`` (same path
the chonky toolbar drives), which keeps the auth refresh-token flow under
the page. The chonky grid is virtualized so we cannot confirm completion
by reading visible names; instead we poll the backend listing endpoint
the same code uses for ``clear_project``.
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


async def open_file_browser(page: Page, *, timeout_s: float = 60.0) -> None:
    """Open the File Browser panel and wait for the Chonky grid to mount."""
    try:
        await page.locator(locators.FILE_BROWSER_ICON).first.click(
            timeout=int(timeout_s * 1000)
        )
    except Exception as exc:
        raise BrowserError(f"could not open File Browser panel: {exc}") from exc

    try:
        await page.locator(locators.CHONKY_ROOT).first.wait_for(
            state="visible", timeout=int(timeout_s * 1000)
        )
    except Exception as exc:
        raise BrowserError(f"File Browser panel never rendered: {exc}") from exc
    logger.info("File Browser panel open")


async def close_file_browser(page: Page, *, timeout_s: float = 10.0) -> None:
    """Close the File Browser panel. No-op if it isn't currently open."""
    chonky = page.locator(locators.CHONKY_ROOT).first
    if not await chonky.is_visible():
        return
    try:
        await page.locator(locators.FILE_BROWSER_ICON).first.click(
            timeout=int(timeout_s * 1000)
        )
    except Exception as exc:
        raise BrowserError(f"could not close File Browser panel: {exc}") from exc
    try:
        await chonky.wait_for(state="hidden", timeout=int(timeout_s * 1000))
    except Exception as exc:
        raise BrowserError(f"File Browser panel never closed: {exc}") from exc
    logger.info("File Browser panel closed")


async def dump_visible_text(page: Page) -> str:
    """Return the raw inner text of the Chonky grid for debugging.

    Chonky class names are webpack-hashed so we don't try to parse the
    tree — a plain text dump is enough to see which files are listed.
    """
    root = page.locator(locators.CHONKY_ROOT).first
    try:
        return (await root.inner_text()).strip()
    except Exception as exc:
        raise BrowserError(f"could not read File Browser contents: {exc}") from exc


_CSRF_HEADER = "X-CSRF-Token"
_CSRF_COOKIE = "csrf_token"


async def _read_csrf_token(page: Page, frontend_url: str) -> str:
    for cookie in await page.context.cookies(frontend_url):
        if cookie.get("name") == _CSRF_COOKIE:
            return cookie.get("value") or ""
    return ""


async def _safe_body(resp: object, limit: int = 200) -> str:
    try:
        return (await resp.text())[:limit]  # type: ignore[attr-defined]
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
    """Fetch with auto-refresh on 401, mirroring pmview's ``callAuthenticatedApiEndpoint``.

    Long-running cases outlive the access-token TTL; without a refresh
    handler, the next API call (typically ``clear_project``'s listing)
    fails the whole case with a 401. We replicate the frontend's flow:
    on 401, ``POST /v3/auth/refresh-token`` (cookies carry the refresh
    token) and replay the original request once with the rotated CSRF.
    """
    headers = dict(kwargs.pop("headers", None) or {})
    headers[_CSRF_HEADER] = await _read_csrf_token(page, frontend_url)
    resp = await page.request.fetch(url, method=method, headers=headers, **kwargs)
    if resp.status != 401:
        return resp
    refresh_resp = await page.request.fetch(
        f"{frontend_url}/v3/auth/refresh-token",
        method="POST",
        headers={_CSRF_HEADER: headers[_CSRF_HEADER]},
    )
    if not refresh_resp.ok:
        return resp
    headers[_CSRF_HEADER] = await _read_csrf_token(page, frontend_url)
    return await page.request.fetch(url, method=method, headers=headers, **kwargs)


async def _list_project_entries(
    page: Page, project: str, frontend_url: str
) -> list[dict[str, Any]]:
    """Fetch immediate children of ``<project>/`` from the backend.

    Returns ``[]`` if the project doesn't exist yet (404). Each entry is a
    dict with at least ``name`` and ``isDir``.
    """
    url = f"{frontend_url}/v3/files?recursive=false&prefix={project}/"
    try:
        resp = await authed_fetch(page, frontend_url, url, method="GET")
    except Exception as exc:
        raise BrowserError(f"GET {url} failed: {exc}") from exc
    if resp.status == 404:
        return []
    if not resp.ok:
        raise BrowserError(
            f"list project files failed: status={resp.status} "
            f"body={await _safe_body(resp)!r}"
        )
    listing = await resp.json()
    if not isinstance(listing, dict):
        raise BrowserError(
            f"list project files: unexpected response shape {type(listing).__name__}; "
            f"sample={str(listing)[:200]!r}"
        )
    return [
        entry for entry in listing.values()
        if isinstance(entry, dict) and "name" in entry
    ]


async def clear_project(page: Page, *, project: str, frontend_url: str) -> int:
    """Delete every file/folder under ``<project>/``. Returns count deleted.

    Mirrors ``fileBrowser.store.deleteProject`` in pmview: list non-recursively
    at the project root, then ``DELETE /v3/file/<project>/<name>`` per entry,
    appending ``/`` for folders so the backend cascades.
    """
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

    The frontend's ``BackendFileBrowser`` mounts a hidden ``<input type=file>``
    that ``uploadFilesToCurrentDirectory`` consumes; passing all paths to
    ``set_input_files`` triggers the same multi-file PUT loop as a manual
    upload. We then poll the backend listing until every basename is
    visible, since the chonky grid is virtualized and unreliable.
    """
    if not local_paths:
        return
    expected = {p.name for p in local_paths}

    await open_file_browser(page)
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
        await close_file_browser(page)


async def download_file(
    page: Page,
    filename: str,
    dest_dir: Path,
    *,
    timeout_s: float = 120.0,
) -> Path:
    """Select a file by visible name and download it via the toolbar.

    The returned path is where the blob was saved inside ``dest_dir``
    (using the browser's suggested filename when available).
    """
    dest_dir.mkdir(parents=True, exist_ok=True)

    row = page.locator(locators.CHONKY_ROOT).first.get_by_text(filename, exact=True).first
    try:
        await row.wait_for(state="visible", timeout=int(timeout_s * 1000))
        await row.click()
    except Exception as exc:
        raise BrowserError(
            f"could not select {filename!r} in File Browser: {exc}"
        ) from exc

    download_button = page.get_by_role(
        locators.DOWNLOAD_SELECTED_BUTTON[0],
        name=locators.DOWNLOAD_SELECTED_BUTTON[1],
    )
    # Chonky enables toolbar actions a tick after the selection event.
    for _ in range(20):
        if await download_button.is_enabled():
            break
        await asyncio.sleep(0.25)

    try:
        async with page.expect_download(timeout=timeout_s * 1000) as info:
            await download_button.click()
        download = await info.value
    except Exception as exc:
        raise BrowserError(f"download of {filename!r} failed: {exc}") from exc

    suggested = download.suggested_filename or filename
    target = dest_dir / suggested
    await download.save_as(str(target))
    logger.info("downloaded %s -> %s", filename, target)
    return target
