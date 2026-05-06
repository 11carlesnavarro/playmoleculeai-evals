"""Drive the pmview sidebar to load and export structures in the viewer.

Plain Playwright actions only, no JS injection into Pyodide or Molstar.

- :func:`load_pdb_id` walks the "Add Files → Get PDB" dialog.
- :func:`load_local_file` uses the hidden file input behind the "Open" menu.
- :func:`export_viewer_state` clicks "Export Viewer State", saves the zip,
  and unzips it next to itself.
- :func:`list_system_names` reads the Pyodide ``systems_tree`` to verify
  what is currently loaded.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pmai_evals._io import parse_json_lenient
from pmai_evals.browser import locators
from pmai_evals.browser.observers import VIEWER_STATE_JSON
from pmai_evals.errors import BrowserError

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)


# pmview's ``exportZip`` prefixes every entry with ``<short_id>_`` where the
# short id is ``Date.now().toString(36)`` (7-10 char base-36).
_EXPORT_PREFIX_RE = re.compile(r"^[0-9a-z]{7,10}_")


def strip_export_prefix(name: str) -> str:
    """Return the logical filename by stripping pmview's exportZip id prefix."""
    return _EXPORT_PREFIX_RE.sub("", name, count=1)


async def _read_systems_tree(page: Page) -> Any:
    return parse_json_lenient(await page.evaluate(VIEWER_STATE_JSON))


async def _wait_for_identifier(page: Page, identifier: str, *, timeout_s: float) -> None:
    needle = identifier.lower()
    deadline = time.monotonic() + timeout_s
    last = ""
    while time.monotonic() < deadline:
        tree = await _read_systems_tree(page)
        last = "" if tree is None else json.dumps(tree)
        if needle in last.lower():
            return
        await asyncio.sleep(0.5)
    raise BrowserError(
        f"identifier {identifier!r} never appeared in systems_tree within "
        f"{timeout_s:.0f}s; last_tree={last[:300]!r}"
    )


async def _open_add_files_menu(page: Page, *, timeout_s: float = 60.0) -> None:
    """Click the sidebar "Add Files" button once Pyodide has enabled it.

    ``exact=True`` is load-bearing: a second per-system "Add files"
    IconButton appears once any structure is loaded and would otherwise
    collide with the sidebar ListItemButton.
    """
    button = page.get_by_role(
        locators.ADD_FILES_BUTTON[0],
        name=locators.ADD_FILES_BUTTON[1],
        exact=True,
    )
    try:
        await button.click(timeout=int(timeout_s * 1000))
    except Exception as exc:
        raise BrowserError(
            f"'Add Files' never became actionable within {timeout_s:.0f}s: {exc}"
        ) from exc


async def load_pdb_id(page: Page, pdb_id: str, *, timeout_s: float = 60.0) -> None:
    """Load ``pdb_id`` into the viewer via the "Get PDB" dialog."""
    logger.info("loading PDB %s via Get PDB dialog", pdb_id)
    try:
        await _open_add_files_menu(page, timeout_s=timeout_s)
        await page.get_by_role(
            locators.GET_PDB_MENU_ITEM[0], name=locators.GET_PDB_MENU_ITEM[1]
        ).click()
        await page.get_by_role(
            locators.PDB_ID_FIELD[0], name=locators.PDB_ID_FIELD[1]
        ).fill(pdb_id)
        await page.get_by_role(
            locators.CONFIRM_BUTTON[0], name=locators.CONFIRM_BUTTON[1]
        ).click()
    except BrowserError:
        raise
    except Exception as exc:
        raise BrowserError(f"load_pdb_id({pdb_id!r}) UI flow failed: {exc}") from exc

    await _wait_for_identifier(page, pdb_id, timeout_s=timeout_s)
    logger.info("PDB %s is visible in systems_tree", pdb_id)


async def load_local_file(page: Page, path: Path, *, timeout_s: float = 60.0) -> None:
    """Upload a local structure file via the hidden file input."""
    logger.info("loading local file %s via Add Files menu", path.name)
    try:
        await _open_add_files_menu(page, timeout_s=timeout_s)
        await page.locator(locators.FILE_UPLOAD_INPUT).set_input_files(str(path))
    except BrowserError:
        raise
    except Exception as exc:
        raise BrowserError(f"load_local_file({path}) UI flow failed: {exc}") from exc

    await _wait_for_identifier(page, path.stem, timeout_s=timeout_s)
    logger.info("local file %s is visible in systems_tree", path.name)


async def list_system_names(page: Page) -> list[str]:
    """Top-level system names currently in ``systems_tree``."""
    tree = await _read_systems_tree(page)
    if not isinstance(tree, list):
        return []
    return [
        entry["name"]
        for entry in tree
        if isinstance(entry, dict) and isinstance(entry.get("name"), str) and entry["name"]
    ]


async def export_viewer_state(
    page: Page,
    dest_dir: Path,
    *,
    timeout_s: float = 120.0,
) -> Path:
    """Save the "Export Viewer State" zip and unzip it next to itself.

    pmview's ``exportZip`` bundles every loaded system in its native format
    plus a ``config.pmv`` manifest. Files inside the archive are prefixed
    with a short base-36 id (see :func:`strip_export_prefix`).

    Handles both pmview variants: a single ``ListItemButton`` and an icon
    button that opens a popup with an "Export Viewer State" menu item.
    """
    from playwright.async_api import TimeoutError as PWTimeout

    dest_dir.mkdir(parents=True, exist_ok=True)
    logger.info("exporting viewer state as zip")

    save_icon = page.locator(locators.EXPORT_VIEWER_ICON).first
    menu_item = page.get_by_role(
        locators.EXPORT_VIEWER_MENU_ITEM[0],
        name=locators.EXPORT_VIEWER_MENU_ITEM[1],
    )

    try:
        async with page.expect_download(timeout=timeout_s * 1000) as info:
            await save_icon.click(timeout=int(timeout_s * 1000))
            # Popup variant adds a menu item; single-button variant has the
            # download already in flight, so swallow the menu timeout.
            try:
                await menu_item.click(timeout=3_000)
            except PWTimeout:
                pass
        download = await info.value
    except Exception as exc:
        raise BrowserError(f"export_viewer_state failed: {exc}") from exc

    target = dest_dir / (download.suggested_filename or "viewer_state.zip")
    await download.save_as(str(target))
    extracted = target.with_suffix("")
    try:
        with zipfile.ZipFile(target) as zf:
            zf.extractall(extracted)
    except zipfile.BadZipFile as exc:
        raise BrowserError(
            f"viewer state archive {target} was not a valid zip: {exc}"
        ) from exc
    logger.info("exported viewer state -> %s (extracted to %s)", target, extracted)
    return target
