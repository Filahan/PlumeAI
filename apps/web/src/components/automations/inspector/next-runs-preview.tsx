'use client';

import { formatRunTime } from './next-runs';

/** "Next 3 runs", computed in the browser from the trigger the user is looking at.
 *  Empty means the expression isn't one of the presets — the header already shows the
 *  server-computed `nextRunAt` for those. */
export default function NextRunsPreview({
  runs,
  timezone,
  approximate = false,
}: {
  runs: number[];
  timezone: string;
  approximate?: boolean;
}) {
  return (
    <div className="rounded-xl border border-[color:var(--border)] px-3 py-2.5">
      <div className="text-[11px] uppercase tracking-[0.08em] text-[color:var(--muted-foreground)]">
        Next 3 runs
      </div>
      {runs.length === 0 ? (
        <p className="mt-1 text-[12px] text-[color:var(--muted-foreground)]">
          Custom schedule — the header shows the next run once it is saved.
        </p>
      ) : (
        <ul className="mt-1 space-y-0.5">
          {runs.map((instant) => (
            <li key={instant} className="text-[12px] tabular-nums">
              {formatRunTime(instant, timezone)}
            </li>
          ))}
        </ul>
      )}
      {approximate && runs.length > 0 && (
        <p className="mt-1 text-[11px] text-[color:var(--muted-foreground)]">
          Approximate: the clock restarts after each run.
        </p>
      )}
    </div>
  );
}
