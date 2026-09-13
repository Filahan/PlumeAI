'use client';

import { Info } from 'lucide-react';
import { zonedClock, zonedDayLabel } from '@/lib/automations/format';

/** "That means" — the next three real fire times of whatever the sentence above says.
 *
 *  Computed in the browser from the draft, so it answers before anything is saved. An
 *  empty list means the expression is not one this evaluator reads (a hand-written cron);
 *  the automation header still shows the server's `nextRunAt` once it is saved. */
export default function SchedulePreview({
  runs,
  timezone,
  now,
  caveat,
}: {
  runs: number[];
  timezone: string;
  now: number;
  caveat?: string | null;
}) {
  return (
    <div className="flex flex-col gap-2">
      <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-[color:var(--muted-foreground)]">
        That means
      </div>

      {runs.length === 0 ? (
        <p className="text-[13px] text-[color:var(--muted-foreground)]">
          This expression is not one we can read ahead. The next run appears once it is saved.
        </p>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {runs.map((instant, index) => (
            <li
              key={instant}
              className="flex items-center gap-2.5 rounded-xl border border-[color:var(--border)] bg-white px-3 py-2.5"
            >
              <span
                aria-hidden
                className="h-1.5 w-1.5 shrink-0 rounded-full"
                style={{ background: index === 0 ? '#6366F1' : 'rgba(138,138,149,0.4)' }}
              />
              <span className="flex-1 truncate text-[13px]">
                {zonedDayLabel(instant, now, timezone)}
              </span>
              <span className="shrink-0 text-[13px] tabular-nums text-[color:var(--muted-foreground)]">
                {zonedClock(instant, timezone)}
              </span>
            </li>
          ))}
        </ul>
      )}

      {caveat && (
        <p className="flex items-center gap-1.5 text-[12px] text-[color:var(--muted-foreground)]">
          <Info size={13} strokeWidth={1.75} aria-hidden className="shrink-0" />
          {caveat}
        </p>
      )}
    </div>
  );
}
