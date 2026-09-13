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

/** "in 12 min" / "in 3 h" / "in 2 d" for a future timestamp; "due now" once it passes. */
export function relativeFuture(ms: number): string {
  const diff = ms - Date.now();
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
