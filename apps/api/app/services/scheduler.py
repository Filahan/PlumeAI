"""Scheduler seam.

# Task 4b replaces this — the real implementation drives an APScheduler AsyncIOScheduler
# that owns one job per enabled automation with a schedule trigger.

Everything that changes an automation's trigger or enabled flag already calls
`sync_job`/`remove_job`, and the API already reads `next_run_at` for its `nextRunAt`
field, so wiring the scheduler in Task 4b is a matter of filling these three functions
in — no call sites move.
"""

from __future__ import annotations

from typing import Any

import structlog

log = structlog.get_logger("app.scheduler")


def sync_job(automation: Any) -> None:
    """Create / update / remove the scheduled job for `automation` to match its document.

    No-op until Task 4b.
    """
    return None


def remove_job(automation_id: str) -> None:
    """Drop any scheduled job for `automation_id`. No-op until Task 4b."""
    return None


def next_run_at(automation_id: str) -> int | None:
    """Next fire time of `automation_id`'s job as epoch ms, or None when it has none.

    Always None until Task 4b.
    """
    return None
