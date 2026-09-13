/** Presentation helpers shared by the automations sidebar, the editor header and the
 *  run panel. Pure functions — no React, no store. */

/** Dot colors keyed by status. A superset of `RunStatus` and `RunStepStatus`, so one
 *  map covers the list rows, the run list and the step rows. */
export const RUN_STATUS_DOT: Record<string, string> = {
  pending: 'bg-[color:var(--muted-foreground)]/40',
  queued: 'bg-[#f59e0b]',
  running: 'bg-[#6366f1] animate-pulse',
  succeeded: 'bg-[#10A37F]',
  failed: 'bg-[#D4183D]',
  skipped: 'bg-[color:var(--muted-foreground)]/40',
  cancelled: 'bg-[color:var(--muted-foreground)]/40',
};

export function statusDot(status: string | null | undefined): string {
  if (!status) return 'bg-[color:var(--muted-foreground)]/25';
  return RUN_STATUS_DOT[status] ?? 'bg-[color:var(--muted-foreground)]/25';
}

export function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60_000).toFixed(1)}m`;
}

/** "just now" / "12m ago" / "3h ago" / "2d ago" for a past timestamp. */
export function relativePast(ms: number): string {
  const diff = Date.now() - ms;
  if (diff < 60_000) return 'just now';
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
  return `${Math.floor(diff / 86_400_000)}d ago`;
}

/** "in 12 min" / "in 3 h" / "in 2 d" for a future timestamp; "due now" once it passes.
 *  `now` is injectable so a caller that has already read the clock (and branches on it)
 *  cannot disagree with this answer by a few milliseconds. */
export function relativeFuture(ms: number, now = Date.now()): string {
  const diff = ms - now;
  if (diff <= 0) return 'due now';
  if (diff < 60_000) return 'in <1 min';
  if (diff < 3_600_000) return `in ${Math.round(diff / 60_000)} min`;
  if (diff < 86_400_000) return `in ${Math.round(diff / 3_600_000)} h`;
  return `in ${Math.round(diff / 86_400_000)} d`;
}

/** Compact JSON for a `<pre>`; falls back to `String()` on cycles. */
export function prettyJson(value: unknown): string {
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value, null, 2) ?? String(value);
  } catch {
    return String(value);
  }
}

// ─── Activity ───────────────────────────────────────────────────────────────────────

const DAY_MS = 86_400_000;

/** "08:00" in the viewer's own timezone. */
export function timeOfDay(ms: number): string {
  return new Date(ms).toLocaleTimeString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}

/** Midnight (local) of the day `ms` falls in. */
export function startOfDay(ms: number): number {
  const d = new Date(ms);
  d.setHours(0, 0, 0, 0);
  return d.getTime();
}

/** When the next run is due, read the way a person would say it:
 *  under a day it stays relative ("in 13 min"), past that it becomes a clock time on a
 *  named day ("tomorrow 08:00", "Monday 09:00", "12 Mar 08:00"). */
export function nextRunLabel(ms: number | null | undefined, now = Date.now()): string {
  if (ms == null) return '—';
  if (ms - now < DAY_MS) return relativeFuture(ms, now);

  const days = Math.round((startOfDay(ms) - startOfDay(now)) / DAY_MS);
  const clock = timeOfDay(ms);
  if (days === 1) return `tomorrow ${clock}`;
  if (days < 7) {
    return `${new Date(ms).toLocaleDateString(undefined, { weekday: 'long' })} ${clock}`;
  }
  return `${new Date(ms).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })} ${clock}`;
}

/** "14 Sep 2026, 16:02", or "not started" — the date half of a run's tooltip. */
export function runMoment(ms: number | null | undefined): string {
  if (ms == null) return 'not started';
  return new Date(ms).toLocaleString(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}

/** One run in a sentence — the title and `aria-label` of every Activity square and mark:
 *  "14 Sep 2026, 16:02 · failed · 1.2s". */
export function runSummaryLine(run: {
  status: string;
  startedAt: number | null;
  durationMs: number | null;
}): string {
  const parts = [runMoment(run.startedAt), run.status];
  if (run.durationMs != null) parts.push(formatDuration(run.durationMs));
  return parts.join(' · ');
}
