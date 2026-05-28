"""Track and cancel PlayMolecule backend jobs from the eval runner.

After the agent stops talking, short jobs (systembuilder, parameterize)
typically still need a few minutes to finish; long jobs (simplerun,
acemd) take hours. The settle phase polls the backend, lets short jobs
finish naturally, and caps each individual job at a wall-clock budget
by POSTing ``/jobs/cancel`` once its observed elapsed exceeds
``job_cap_s``.

Routes used (same path the pmview frontend hits at
``highPriorityWorker.ts:227`` and ``CancelJob.tsx:15``; the frontend
forwards ``/v3/...`` to the PlayMolecule backend, so the eval runner's
browser session has the right cookies and CSRF to reuse them):

* ``GET  {frontend_url}/v3/jobs?prefix=<project>/``
* ``POST {frontend_url}/v3/jobs/cancel?job_dir=<job_id>``

The agent server's own ``/v1/backend/...`` proxy is **not** reusable
here — it requires a ``chat_request_id`` header that only the
sandboxed agent process possesses.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any, Literal

from pmai_evals.browser.project_files import authed_fetch
from pmai_evals.errors import BrowserError

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)


# Status codes the backend reports for "still in flight" jobs.
# Mirrors playmoleculeai/tools/core/job_tracker.py:152 (ACTIVE_JOB_STATUS).
_ACTIVE_JOB_STATUS: frozenset[int] = frozenset({0, 1})

_POLL_INTERVAL_S = 3.0

ExitReason = Literal["settled", "build_wait_exceeded", "no_jobs", "fetch_failed"]


@dataclass(frozen=True, slots=True)
class JobsSettleReport:
    """Outcome of the settle phase. Serialised into ``metrics.json``."""

    jobs_seen: int
    jobs_cancelled: int
    settle_elapsed_s: float
    exit_reason: ExitReason

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


async def list_active_jobs(
    page: Page, frontend_url: str, project: str
) -> list[dict[str, Any]]:
    """Active backend jobs whose ``job_id`` lives under ``<project>/``.

    Returns ``[]`` on 404 (the prefix has no jobs at all). Raises
    :class:`BrowserError` on any other non-2xx response.
    """
    url = f"{frontend_url}/v3/jobs?prefix={project}/"
    try:
        resp = await authed_fetch(page, frontend_url, url, method="GET")
    except Exception as exc:
        raise BrowserError(f"GET {url} failed: {exc}") from exc
    if resp.status == 404:
        return []
    if not resp.ok:
        raise BrowserError(f"list jobs failed: status={resp.status}")
    try:
        data = await resp.json()
    except Exception as exc:
        raise BrowserError(f"jobs list body was not JSON: {exc}") from exc

    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        rows = list(data.values())
    else:
        raise BrowserError(
            f"jobs list unexpected shape: {type(data).__name__}"
        )

    out: list[dict[str, Any]] = []
    for j in rows:
        if not isinstance(j, dict):
            continue
        try:
            status = int(j.get("status"))
        except (TypeError, ValueError):
            continue
        if status in _ACTIVE_JOB_STATUS:
            out.append(j)
    return out


async def cancel_job(page: Page, frontend_url: str, job_id: str) -> bool:
    """POST ``/jobs/cancel?job_dir=<job_id>``. Returns ``True`` on 2xx."""
    url = f"{frontend_url}/v3/jobs/cancel?job_dir={job_id}"
    try:
        resp = await authed_fetch(page, frontend_url, url, method="POST")
    except Exception as exc:
        logger.warning("cancel_job %s raised: %s", job_id, exc)
        return False
    if not resp.ok:
        logger.warning("cancel_job %s failed: status=%d", job_id, resp.status)
        return False
    return True


async def wait_for_jobs_or_cap(
    *,
    page: Page,
    frontend_url: str,
    project: str,
    build_wait_s: int,
    job_cap_s: int,
) -> JobsSettleReport:
    """After the agent stops, settle backend jobs with a per-job cap.

    Polls every ``_POLL_INTERVAL_S`` seconds. Each job's
    first-observed timestamp is recorded; any job whose observed
    elapsed exceeds ``job_cap_s`` is cancelled. The loop exits when:

    * no jobs were active on the first poll (``no_jobs``); or
    * the active list becomes empty (``settled``); or
    * total elapsed exceeds ``build_wait_s`` — every job still
      active is then cancelled before return (``build_wait_exceeded``).
    """
    started = time.monotonic()
    first_seen: dict[str, float] = {}
    cancelled: set[str] = set()

    try:
        initial = await list_active_jobs(page, frontend_url, project)
    except BrowserError as exc:
        logger.warning("settle: initial list_active_jobs failed: %s", exc)
        return JobsSettleReport(
            jobs_seen=0,
            jobs_cancelled=0,
            settle_elapsed_s=time.monotonic() - started,
            exit_reason="fetch_failed",
        )

    if not initial:
        return JobsSettleReport(
            jobs_seen=0,
            jobs_cancelled=0,
            settle_elapsed_s=time.monotonic() - started,
            exit_reason="no_jobs",
        )

    now = time.monotonic()
    for j in initial:
        job_id = j.get("job_id", "")
        if job_id:
            first_seen.setdefault(job_id, now)

    while True:
        if time.monotonic() - started > build_wait_s:
            try:
                active = await list_active_jobs(page, frontend_url, project)
            except BrowserError as exc:
                logger.warning("settle: final list_active_jobs failed: %s", exc)
                active = []
            for j in active:
                job_id = j.get("job_id", "")
                if not job_id or job_id in cancelled:
                    continue
                if await cancel_job(page, frontend_url, job_id):
                    cancelled.add(job_id)
            return JobsSettleReport(
                jobs_seen=len(first_seen),
                jobs_cancelled=len(cancelled),
                settle_elapsed_s=time.monotonic() - started,
                exit_reason="build_wait_exceeded",
            )

        await asyncio.sleep(_POLL_INTERVAL_S)

        try:
            active = await list_active_jobs(page, frontend_url, project)
        except BrowserError as exc:
            logger.warning("settle: list_active_jobs failed: %s", exc)
            continue

        if not active:
            return JobsSettleReport(
                jobs_seen=len(first_seen),
                jobs_cancelled=len(cancelled),
                settle_elapsed_s=time.monotonic() - started,
                exit_reason="settled",
            )

        now = time.monotonic()
        for j in active:
            job_id = j.get("job_id", "")
            if not job_id:
                continue
            first_seen.setdefault(job_id, now)
            if job_id in cancelled:
                continue
            if now - first_seen[job_id] > job_cap_s:
                logger.info(
                    "settle: cancelling job %s (elapsed %.1fs > cap %ds)",
                    job_id, now - first_seen[job_id], job_cap_s,
                )
                if await cancel_job(page, frontend_url, job_id):
                    cancelled.add(job_id)
