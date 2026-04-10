"""Upload fixture files into the project workspace before a chat starts.

playmoleculeAI fixtures live in the user's project bucket. The frontend's
file upload affordance is the most user-faithful path; we use that here.
If a future eval needs to bypass the UI (e.g. very large fixtures), add a
direct backend upload helper rather than touching this file.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from pmai_evals.config import Settings
from pmai_evals.errors import BrowserError

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)


async def upload_fixtures_for_chat(
    page: Page,
    fixtures: Sequence[Path],
    settings: Settings,
    project: str,
) -> None:
    """Upload one or more files via the chat's attach affordance.

    Best-effort: if no file input is exposed, log a warning. The runner
    treats fixture upload as a soft dependency — the case may still
    proceed and either succeed (if the agent can fetch the file by name)
    or fail with a clear assertion failure.
    """

    if not fixtures:
        return

    for fixture in fixtures:
        if not fixture.exists():
            raise BrowserError(f"fixture missing on disk: {fixture}")

    try:
        # Look for the standard MUI hidden file input. Adjust the locator
        # if the frontend changes — keep the change here, not in callers.
        file_input = page.locator("input[type='file']").first
        if await file_input.count() == 0:
            logger.warning(
                "no file input found on page; skipping fixture upload (%d files)",
                len(fixtures),
            )
            return
        await file_input.set_input_files([str(f) for f in fixtures])
        logger.info(
            "uploaded %d fixture(s) to project=%s",
            len(fixtures),
            project,
        )
    except Exception as exc:
        raise BrowserError(f"fixture upload failed: {exc}") from exc
