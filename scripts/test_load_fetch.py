"""Smoke test for the viewer-loader and project-files browser primitives.

Exercises the real pmview UI end-to-end in a single Playwright session:

    1. Open a fresh page via :class:`PMBrowser`.
    2. ``load_pdb_id`` a PDB entry through the "Get PDB" dialog.
    3. ``load_local_file`` a structure file via the hidden file input.
    4. ``open_file_browser`` to route to the File Browser panel.
    5. Optionally ``download_file`` a named file from the project bucket
       into a local destination directory.

The script prints each step's result and saves a screenshot after every
major action for visual debugging. It is intentionally standalone — no
``cases.yaml``, no assertions, no grading — so we can iterate on the
primitives without dragging the whole runner along.

Example:

    uv run python scripts/test_load_fetch.py \\
        --pdb-id 1CRN \\
        --local-file eval_sets/molecular-visualization/fixtures/ligand.sdf \\
        --download-name 1CRN.pdb \\
        --dest-dir ./runs/_smoke
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from pmai_evals.browser.project_files import (
    download_file,
    dump_visible_text,
    open_file_browser,
    upload_to_project,
)
from pmai_evals.browser.session import PMBrowser
from pmai_evals.browser.viewer_loader import (
    download_viewer_system,
    export_viewer_state,
    load_local_file,
    load_pdb_id,
)
from pmai_evals.config import Settings

logger = logging.getLogger("test_load_fetch")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pdb-id",
        default="1CRN",
        help="PDB entry to load via the Get PDB dialog (default: 1CRN).",
    )
    parser.add_argument(
        "--local-file",
        type=Path,
        default=Path("eval_sets/molecular-visualization/fixtures/ligand.sdf"),
        help="Local structure file to upload via the hidden file input.",
    )
    parser.add_argument(
        "--download-name",
        default=None,
        help=(
            "Exact visible name of a file to download from the File Browser "
            "after the loads. Omit to skip the project-file download step."
        ),
    )
    parser.add_argument(
        "--upload-file",
        type=Path,
        default=None,
        help=(
            "Local file to upload into the project bucket via the File "
            "Browser's Chonky Upload toolbar path. If set, the script "
            "also downloads it back and verifies the bytes round-trip."
        ),
    )
    parser.add_argument(
        "--viewer-system",
        default=None,
        help=(
            "Name of a single in-viewer system to download via the ⋮ → "
            "Download menu. Omit and use --download-all-viewer instead "
            "when the names aren't known ahead of time."
        ),
    )
    parser.add_argument(
        "--export-viewer-state",
        action="store_true",
        help=(
            "Click the sidebar 'Export Viewer State' button and save the "
            "resulting zip (all loaded systems + config.pmv)."
        ),
    )
    parser.add_argument(
        "--viewer-system-format",
        default="pdb",
        help="File format to request in SaveSystemDialog (default: pdb).",
    )
    parser.add_argument(
        "--dest-dir",
        type=Path,
        default=Path("runs/_smoke"),
        help="Directory to save the downloaded file and step screenshots.",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Run Chromium headed for visual debugging.",
    )
    parser.add_argument(
        "--skip-pdb",
        action="store_true",
        help="Skip the load_pdb_id step.",
    )
    parser.add_argument(
        "--skip-local",
        action="store_true",
        help="Skip the load_local_file step.",
    )
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> int:
    settings = Settings()
    if args.headed:
        settings.pmai_evals_headless = False

    args.dest_dir.mkdir(parents=True, exist_ok=True)

    async with PMBrowser(settings) as browser:
        await browser.ensure_authenticated()
        chat = await browser.new_chat(model="smoke", project=settings.pm_project)
        page = chat.page
        try:
            await page.screenshot(path=str(args.dest_dir / "00_initial.png"))

            if not args.skip_pdb:
                logger.info("--- step 1: load_pdb_id(%s) ---", args.pdb_id)
                await load_pdb_id(page, args.pdb_id)
                await page.screenshot(path=str(args.dest_dir / "01_pdb_loaded.png"))

            if not args.skip_local:
                logger.info("--- step 2: load_local_file(%s) ---", args.local_file)
                await load_local_file(page, args.local_file)
                await page.screenshot(
                    path=str(args.dest_dir / "02_local_loaded.png")
                )

            if args.export_viewer_state:
                logger.info("--- step 3: export_viewer_state ---")
                saved_zip = await export_viewer_state(page, args.dest_dir)
                logger.info("viewer state zip saved to %s", saved_zip)
                await page.screenshot(
                    path=str(args.dest_dir / "03_viewer_export.png")
                )
            elif args.viewer_system:
                logger.info(
                    "--- step 3: download_viewer_system(%s, format=%s) ---",
                    args.viewer_system,
                    args.viewer_system_format,
                )
                saved = await download_viewer_system(
                    page,
                    args.viewer_system,
                    args.dest_dir,
                    file_format=args.viewer_system_format,
                )
                logger.info("viewer system saved to %s", saved)
                await page.screenshot(
                    path=str(args.dest_dir / "03_viewer_download.png")
                )
            else:
                logger.info(
                    "--- step 3: skipped (pass --viewer-system or --export-viewer-state) ---"
                )

            logger.info("--- step 4: open_file_browser ---")
            await open_file_browser(page)
            await page.screenshot(
                path=str(args.dest_dir / "04_file_browser.png")
            )
            visible = await dump_visible_text(page)
            logger.info("file browser contents:\n%s", visible or "<empty>")

            if args.upload_file:
                logger.info(
                    "--- step 5: upload_to_project(%s) + round-trip download ---",
                    args.upload_file,
                )
                await upload_to_project(page, args.upload_file)
                await page.screenshot(
                    path=str(args.dest_dir / "05_after_upload.png")
                )
                roundtrip = await download_file(
                    page, args.upload_file.name, args.dest_dir
                )
                logger.info("round-tripped to %s", roundtrip)
                original_bytes = args.upload_file.read_bytes()
                roundtrip_bytes = roundtrip.read_bytes()
                if original_bytes == roundtrip_bytes:
                    logger.info(
                        "round-trip OK: %d bytes match", len(original_bytes)
                    )
                else:
                    logger.warning(
                        "round-trip MISMATCH: original=%d bytes, downloaded=%d bytes",
                        len(original_bytes),
                        len(roundtrip_bytes),
                    )
            else:
                logger.info("--- step 5: skipped (no --upload-file) ---")

            if args.download_name:
                logger.info("--- step 6: download_file(%s) ---", args.download_name)
                saved = await download_file(
                    page, args.download_name, args.dest_dir
                )
                logger.info("downloaded to %s", saved)
            else:
                logger.info("--- step 6: skipped (no --download-name) ---")

        finally:
            await chat.close()

    logger.info("smoke test OK; artifacts in %s", args.dest_dir)
    return 0


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = _parse_args()
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        logger.warning("interrupted")
        return 130
    except Exception as exc:
        logger.error("smoke test FAILED: %s", exc, exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
