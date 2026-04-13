"""Drive the pmview sidebar + systems panel to move structures in and out
of the Molstar viewer.

Plain Playwright actions only — no JS injection into Pyodide or Molstar.

- :func:`load_pdb_id` walks the "Add Files → Get PDB" dialog.
- :func:`load_local_file` opens the same menu and uses the hidden file
  input (``#raised-button-file``) exposed by ``LoadFileMenuItem``.
- :func:`download_viewer_system` drives the per-system "⋮ → Download"
  flow in the left Systems panel, which serializes whatever is currently
  in Molstar/Pyodide (regardless of whether the bytes were ever
  persisted to the project bucket) and returns them as a local file.

The load helpers wait until the new entry appears in the Pyodide-backed
``systems_tree`` before returning; the download helper waits on the
browser's download event.
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


# pmview's ``exportZip`` prefixes every file in the archive with
# ``<short_id>_`` where the short id is ``Date.now().toString(36)`` — a
# 7-10 char base-36 string from ``pmview/.../Export/utils.ts::createShortUniqueId``.
# Example: ``mnx67k75_1CRN.cif`` → logical name ``1CRN.cif``.
_EXPORT_PREFIX_RE = re.compile(r"^[0-9a-z]{7,10}_")


def strip_export_prefix(name: str) -> str:
    """Return the logical filename by stripping pmview's exportZip id prefix.

    ``name`` is a basename, not a path. If the prefix doesn't match, the
    input is returned unchanged — safe to call on ``config.pmv`` and
    other un-prefixed entries.
    """
    return _EXPORT_PREFIX_RE.sub("", name, count=1)


async def _read_systems_tree(page: Page) -> Any:
    """Return the Pyodide ``systems_tree`` as a Python value (list / dict / None)."""
    return parse_json_lenient(await page.evaluate(VIEWER_STATE_JSON))


async def _wait_for_identifier(
    page: Page, identifier: str, *, timeout_s: float
) -> None:
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

    The button is ``disabled={!pyodideReady}`` and is covered by the
    full-screen MolkitLoaderStatus backdrop until the Pyodide worker is
    live. Playwright's actionability check handles the backdrop, but we
    still give it a generous window because cold Pyodide can take a while.
    """
    # ``exact=True`` is load-bearing: once a structure is loaded, a second
    # per-system IconButton with aria-label "Add files" (lowercase 'f')
    # appears and collides with the sidebar "Add Files" ListItemButton.
    button = page.get_by_role(
        locators.ADD_FILES_BUTTON[0],
        name=locators.ADD_FILES_BUTTON[1],
        exact=True,
    )
    try:
        await button.click(timeout=int(timeout_s * 1000))
    except Exception as exc:
        raise BrowserError(
            f"'Add Files' button never became actionable within {timeout_s:.0f}s: {exc}"
        ) from exc


async def load_pdb_id(
    page: Page, pdb_id: str, *, timeout_s: float = 60.0
) -> None:
    """Load ``pdb_id`` into the viewer via the "Get PDB" dialog."""
    logger.info("loading PDB %s via Get PDB dialog", pdb_id)
    try:
        await _open_add_files_menu(page, timeout_s=timeout_s)
        await page.get_by_role(
            locators.GET_PDB_MENU_ITEM[0], name=locators.GET_PDB_MENU_ITEM[1]
        ).click()
        field = page.get_by_role(
            locators.PDB_ID_FIELD[0], name=locators.PDB_ID_FIELD[1]
        )
        await field.fill(pdb_id)
        await page.get_by_role(
            locators.CONFIRM_BUTTON[0], name=locators.CONFIRM_BUTTON[1]
        ).click()
    except BrowserError:
        raise
    except Exception as exc:
        raise BrowserError(f"load_pdb_id({pdb_id!r}) UI flow failed: {exc}") from exc

    await _wait_for_identifier(page, pdb_id, timeout_s=timeout_s)
    logger.info("PDB %s is visible in systems_tree", pdb_id)


async def load_local_file(
    page: Page, path: Path, *, timeout_s: float = 60.0
) -> None:
    """Upload a local structure file via the hidden ``#raised-button-file`` input.

    The input lives inside the "Add Files → Open" menu item, so we open
    the menu first to ensure the element is mounted in the DOM. Setting
    the file fires ``onChange`` directly, which routes through
    ``fileUploadingHandler`` and closes the menu.
    """
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


def _system_more_button(page: Page, system_name: str):
    """Return a locator for the "⋮" more-options button on a given system row.

    Strategy: find any element whose normalized text equals ``system_name``
    (the row label) or any input whose ``value`` matches (the in-place
    rename field), climb to the nearest ancestor that also contains a
    ``MoreVertIcon`` — that ancestor is the row container — and pick the
    button wrapping the icon inside it. This avoids a dependency on
    pmview-internal class names.
    """
    name_literal = system_name.replace("'", "\\'")
    row_xpath = (
        "xpath=("
        f"//input[@value='{name_literal}']"
        f"|//*[normalize-space(text())='{name_literal}']"
        f")[1]/ancestor-or-self::*[.//*[@data-testid='MoreVertIcon']][1]"
    )
    row = page.locator(row_xpath).first
    return row.locator("button").filter(has=page.locator(locators.SYSTEM_MORE_ICON)).first


async def download_viewer_system(
    page: Page,
    system_name: str,
    dest_dir: Path,
    *,
    file_format: str = "pdb",
    timeout_s: float = 120.0,
) -> Path:
    """Download a system currently loaded in Molstar via its "⋮ → Download" menu.

    The download is produced in-browser: pmview asks Pyodide to
    ``save_molecule`` the system into the virtual FS, reads the bytes,
    wraps them in a ``Blob``, and fires a programmatic anchor click.
    ``page.expect_download()`` captures the resulting download event.

    ``system_name`` must match what the systems panel renders for the
    row (e.g. "1crn" after a Get-PDB load, or the stem of an uploaded
    file). ``file_format`` is whatever the SaveSystemDialog's Autocomplete
    accepts — typically "pdb", "sdf", "cif", "mol2".
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    logger.info(
        "downloading viewer system %r as %s", system_name, file_format
    )

    try:
        more_btn = _system_more_button(page, system_name)
        await more_btn.click(timeout=int(timeout_s * 1000))
    except Exception as exc:
        raise BrowserError(
            f"could not open ⋮ menu for system {system_name!r}: {exc}"
        ) from exc

    try:
        await page.get_by_role(
            locators.SYSTEM_DOWNLOAD_MENU_ITEM[0],
            name=locators.SYSTEM_DOWNLOAD_MENU_ITEM[1],
        ).click(timeout=int(timeout_s * 1000))
    except Exception as exc:
        raise BrowserError(
            f"Download menu item missing for system {system_name!r}: {exc}"
        ) from exc

    try:
        fmt_field = page.locator(locators.SAVE_FORMAT_FIELD)
        await fmt_field.click()
        await fmt_field.fill(file_format)
        option = page.get_by_role("option", name=file_format)
        if await option.count() > 0:
            await option.first.click()
        else:
            await fmt_field.press("Enter")
    except Exception as exc:
        raise BrowserError(
            f"could not set download format to {file_format!r}: {exc}"
        ) from exc

    confirm = page.get_by_role(
        locators.CONFIRM_BUTTON[0], name=locators.CONFIRM_BUTTON[1]
    )
    try:
        async with page.expect_download(timeout=timeout_s * 1000) as info:
            await confirm.click()
        download = await info.value
    except Exception as exc:
        raise BrowserError(
            f"download of system {system_name!r} failed: {exc}"
        ) from exc

    suggested = download.suggested_filename or f"{system_name}.{file_format}"
    target = dest_dir / suggested
    await download.save_as(str(target))
    logger.info("downloaded viewer system %s -> %s", system_name, target)

    # SaveSystemDialog has a bug: ``handleClose`` is commented out on the
    # success path (SaveSystemDialog.tsx:106), so the dialog overlay stays
    # mounted and intercepts pointer events for any follow-up action.
    # Dismiss it explicitly — Escape triggers MUI Dialog's onClose.
    try:
        await page.keyboard.press("Escape")
    except Exception as exc:
        logger.debug("could not dismiss SaveSystemDialog: %s", exc)

    return target


async def list_system_names(page: Page) -> list[str]:
    """Return the top-level system names currently in ``systems_tree``.

    The Pyodide-backed systems tree is a list of dicts, each with a
    ``name`` key (see ``runs/.../viewer_state.json`` samples). Nested /
    grouped children are not expanded.
    """
    tree = await _read_systems_tree(page)
    if not isinstance(tree, list):
        return []
    return [
        entry["name"]
        for entry in tree
        if isinstance(entry, dict)
        and isinstance(entry.get("name"), str)
        and entry["name"]
    ]


async def download_all_viewer_systems(
    page: Page,
    dest_dir: Path,
    *,
    file_format: str = "pdb",
    timeout_s: float = 120.0,
) -> list[Path]:
    """Download every top-level system currently loaded in the viewer.

    Useful when the eval prompt may have renamed systems or loaded extra
    ones — just grab everything Molstar is holding and let the grader
    sort it out downstream.
    """
    names = await list_system_names(page)
    if not names:
        raise BrowserError("no systems found in systems_tree to download")
    saved: list[Path] = []
    for name in names:
        path = await download_viewer_system(
            page,
            name,
            dest_dir,
            file_format=file_format,
            timeout_s=timeout_s,
        )
        saved.append(path)
    logger.info("downloaded %d viewer system(s) to %s", len(saved), dest_dir)
    return saved


async def export_viewer_state(
    page: Page,
    dest_dir: Path,
    *,
    timeout_s: float = 120.0,
) -> Path:
    """Click the sidebar "Export Viewer State" button and save the zip.

    pmview's ``exportZip`` bundles every loaded system **in its native
    format** into a single ``pmv_<timestamp>.zip`` and fires it as a blob
    download. Entries in the archive use whichever extension is right
    for the system kind:

    - proteins / macromolecules → ``.cif``
    - small molecules / ligands → ``.sdf``
    - trajectories → ``.xtc``
    - tables → ``.csv``
    - plots → ``.json`` / ``.png``
    - viewer-state manifest → ``config.pmv`` at the zip root

    Every system file is prefixed with a short base-36 id plus an
    underscore, e.g. ``mnx67k75_1CRN.cif``. Use :func:`strip_export_prefix`
    to recover the logical name when matching files by expected name.

    This is the preferred "save everything" primitive for evals: it
    sidesteps per-system format choices entirely and gives the grader
    one self-describing archive. The archive is unzipped next to itself
    and the returned Path points at the ``.zip``; the extracted
    directory is the same path with the ``.zip`` suffix removed.

    Handles both pmview sidebar variants:
    - single ``ListItemButton`` with tooltip "Export Viewer State"
    - icon button with tooltip "Export" that opens a popup containing
      an "Export Viewer State" ``MenuItem``.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    logger.info("exporting viewer state as zip")

    save_icon = page.locator(locators.EXPORT_VIEWER_ICON).first
    menu_item = page.get_by_role(
        locators.EXPORT_VIEWER_MENU_ITEM[0],
        name=locators.EXPORT_VIEWER_MENU_ITEM[1],
    )

    from playwright.async_api import TimeoutError as PWTimeout

    try:
        async with page.expect_download(timeout=timeout_s * 1000) as info:
            await save_icon.click(timeout=int(timeout_s * 1000))
            # Popup variant: a menu item appears after the click. Single-
            # button variant: the download is already in flight, so the
            # menu click times out — the swallow is intentional.
            try:
                await menu_item.click(timeout=3_000)
            except PWTimeout:
                pass
        download = await info.value
    except Exception as exc:
        raise BrowserError(f"export_viewer_state failed: {exc}") from exc

    suggested = download.suggested_filename or "viewer_state.zip"
    target = dest_dir / suggested
    await download.save_as(str(target))
    logger.info("exported viewer state -> %s", target)

    extracted = target.with_suffix("")
    try:
        with zipfile.ZipFile(target) as zf:
            zf.extractall(extracted)
    except zipfile.BadZipFile as exc:
        raise BrowserError(
            f"viewer state archive {target} was not a valid zip: {exc}"
        ) from exc
    logger.info("extracted viewer state -> %s", extracted)

    inventory = sorted(
        (p.relative_to(extracted), p.stat().st_size)
        for p in extracted.rglob("*")
        if p.is_file()
    )
    if inventory:
        lines = []
        for rel, size in inventory:
            logical = strip_export_prefix(rel.name)
            if logical != rel.name:
                lines.append(f"  {rel}  ({size} bytes)  [logical: {logical}]")
            else:
                lines.append(f"  {rel}  ({size} bytes)")
        logger.info("viewer state contents:\n%s", "\n".join(lines))
    else:
        logger.warning("viewer state archive was empty")

    return target
