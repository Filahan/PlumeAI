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

// ─── Schedules ──────────────────────────────────────────────────────────────────────

/** The calendar day `ms` falls on in `timezone`, as `2026-09-15`. Sortable, and the
 *  only honest way to compare two instants by day when the zone is not the viewer's. */
function dayKey(ms: number, timezone?: string): string {
  try {
    return new Intl.DateTimeFormat('en-CA', {
      timeZone: timezone,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    }).format(new Date(ms));
  } catch {
    return new Intl.DateTimeFormat('en-CA', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    }).format(new Date(ms));
  }
}

/** Whole days between the calendar day of `now` and that of `ms`, in `timezone`. */
export function dayOffset(ms: number, now: number, timezone?: string): number {
  const [a, b] = [dayKey(now, timezone), dayKey(ms, timezone)].map((key) => {
    const [year, month, day] = key.split('-').map(Number);
    return Date.UTC(year, month - 1, day);
  });
  return Math.round((b - a) / 86_400_000);
}

/** "08:00" on the clock in `timezone` — the workspace zone, not the viewer's, because
 *  that is the one the schedule was written in. */
export function zonedClock(ms: number, timezone?: string): string {
  try {
    return new Intl.DateTimeFormat('en-GB', {
      timeZone: timezone,
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    }).format(new Date(ms));
  } catch {
    return timeOfDay(ms);
  }
}

/** "Monday 15 September" — day before month, and no comma before the number.
 *
 *  Pinned to en-GB rather than the viewer's locale on purpose: these strings are read
 *  inside an English sentence ("Tomorrow, Monday 15 September"), and en-US would make it
 *  "Tomorrow, Monday, September 15" — two commas doing different jobs. */
function zonedDate(ms: number, timezone: string | undefined, withWeekday: boolean): string {
  const options: Intl.DateTimeFormatOptions = { day: 'numeric', month: 'long' };
  if (withWeekday) options.weekday = 'long';
  try {
    return new Intl.DateTimeFormat('en-GB', { ...options, timeZone: timezone }).format(
      new Date(ms)
    );
  } catch {
    return new Intl.DateTimeFormat('en-GB', options).format(new Date(ms));
  }
}

/** The left half of a "That means" row: "Today, Monday 15 September", "Tomorrow, …",
 *  or just "Tuesday 16 September" once it is further out than that. */
export function zonedDayLabel(ms: number, now: number, timezone?: string): string {
  const offset = dayOffset(ms, now, timezone);
  const date = zonedDate(ms, timezone, true);
  if (offset === 0) return `Today, ${date}`;
  if (offset === 1) return `Tomorrow, ${date}`;
  return date;
}

/** The absolute line under the relative one: "today 17:15", "tomorrow 08:00",
 *  "Monday 09:00", "12 March 08:00". */
export function dayClockLabel(ms: number, now: number, timezone?: string): string {
  const offset = dayOffset(ms, now, timezone);
  const clock = zonedClock(ms, timezone);
  if (offset === 0) return `today ${clock}`;
  if (offset === 1) return `tomorrow ${clock}`;
  if (offset > 1 && offset < 7) {
    try {
      const weekday = new Intl.DateTimeFormat('en-GB', {
        timeZone: timezone,
        weekday: 'long',
      }).format(new Date(ms));
      return `${weekday} ${clock}`;
    } catch {
      /* fall through to the dated form */
    }
  }
  return `${zonedDate(ms, timezone, false)} ${clock}`;
}

/** The Last result cell: "Worked, 12s", "Failed ×4", "Failed", or "—" when it has
 *  never run. `failures` is the run of consecutive failures the feed reports, and is
 *  only spelled out once there is more than one. */
export function lastResultLabel(
  last: { status: string; durationMs: number | null } | null | undefined,
  failures = 0
): string {
  if (!last) return '—';
  if (last.status === 'failed') return failures > 1 ? `Failed ×${failures}` : 'Failed';
  if (last.status === 'succeeded') {
    return last.durationMs != null ? `Worked, ${formatDuration(last.durationMs)}` : 'Worked';
  }
  return capitalizeFirst(last.status);
}

/** Text color for a Last result cell — muted while the schedule is paused, because a
 *  green "Worked" next to a switch that is off reads as "this is running". */
export function lastResultTone(status: string | null | undefined, enabled: boolean): string {
  if (!enabled || !status) return 'text-[color:var(--muted-foreground)]';
  if (status === 'succeeded') return 'text-[#10A37F]';
  if (status === 'failed') return 'text-[#D4183D]';
  return 'text-[color:var(--muted-foreground)]';
}

function capitalizeFirst(text: string): string {
  return text.length === 0 ? text : text[0].toUpperCase() + text.slice(1);
}
