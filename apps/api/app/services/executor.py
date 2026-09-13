"""Execution-engine seam.

# Task 4b replaces this — the real implementation walks the run's snapshotted document
# step by step (resolving refs, calling actions/AI/filters), writes `run_steps` rows as
# it goes and publishes progress through `app.services.run_events`.

Task 4a persists everything a run needs (`runs` + `run_steps`, created `queued`/`pending`
by `app.services.runs.create_run`) and the API already hands off to
`start_run_in_background` and `request_cancel`, so Task 4b plugs in here without
touching the router.
"""

from __future__ import annotations

import structlog

log = structlog.get_logger("app.executor")


def start_run_in_background(run_id: str) -> None:
    """Kick off execution of an already-created `queued` run. No-op until Task 4b."""
    log.info("executor_not_wired_yet", run_id=run_id)


def request_cancel(run_id: str) -> bool:
    """Ask a *running* run to stop; True when a live run was signalled.

    Always False until Task 4b — there is nothing running in-process to signal.
    """
    log.info("executor_cancel_not_wired_yet", run_id=run_id)
    return False
