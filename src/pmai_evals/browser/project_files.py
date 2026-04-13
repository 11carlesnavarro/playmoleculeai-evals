"""Drive the pmview File Browser panel to move project files in and out.

Everything goes through the same browser path a human eval reviewer
would use; there are no direct backend calls, no filesystem peeking.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

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


async def _wait_for_visible_name(
    page: Page, name: str, *, timeout_s: float
) -> None:
    deadline = time.monotonic() + timeout_s
    last = ""
    while time.monotonic() < deadline:
        last = await dump_visible_text(page)
        if name in last:
            return
        await asyncio.sleep(0.5)
    raise BrowserError(
        f"{name!r} never appeared in File Browser within {timeout_s:.0f}s; "
        f"last grid text={last[:300]!r}"
    )


async def upload_to_project(
    page: Page,
    path: Path,
    *,
    timeout_s: float = 60.0,
) -> None:
    """Upload ``path`` into the project's current File Browser directory.

    Requires :func:`open_file_browser` to have been called first so
    ``BackendFileBrowser`` is mounted — its hidden ``<input type="file">``
    is the target we drive. The Chonky toolbar "Upload" button is a
    cosmetic wrapper that clicks the same input, so we skip it and
    ``set_input_files`` directly. The upload persists via
    ``PUT /v3/file/{folder}/{name}`` and we wait until the filename
    appears in the grid before returning.
    """
    logger.info("uploading %s to project File Browser", path.name)
    try:
        await page.locator(locators.PROJECT_UPLOAD_INPUT).first.set_input_files(
            str(path)
        )
    except Exception as exc:
        raise BrowserError(f"upload of {path} failed: {exc}") from exc

    await _wait_for_visible_name(page, path.name, timeout_s=timeout_s)
    logger.info("uploaded %s is visible in File Browser", path.name)


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
