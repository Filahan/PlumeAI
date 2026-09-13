'use client';

import { useRouter } from 'next/navigation';
import { HOUR_TICKS, runHref, type DayLane } from '@/lib/activity/derive';
import { runSummaryLine, statusDot } from '@/lib/automations/format';

/** Label column + track, shared by the axis and every lane so the marks line up with
 *  the hours above them. */
const LANE_GRID = 'grid grid-cols-[190px_minmax(0,1fr)] items-center gap-4';

const LEGEND: { status: string; label: string }[] = [
  { status: 'succeeded', label: 'Succeeded' },
  { status: 'failed', label: 'Failed' },
  { status: 'running', label: 'Running' },
  { status: 'skipped', label: 'Stopped by a filter' },
];

/** Today as a single ruler: one lane per automation that ran, one mark per run, placed
 *  at the time of day it started.
 *
 *  Marks are positioned in percentages of the day rather than pixels, so the whole thing
 *  reflows with the window and never needs a measured width. */
export default function DayTimeline({ lanes }: { lanes: DayLane[] }) {
  const router = useRouter();

  return (
    <section className="flex flex-col gap-2.5 rounded-2xl border border-[color:var(--border)] bg-white px-5 py-4">
      <div className="flex items-baseline justify-between gap-4">
        <h2 className="text-[13px] font-medium">Today, hour by hour</h2>
        <p className="text-[12px] text-[color:var(--muted-foreground)]">
          One mark per run, widened so short runs stay visible
        </p>
      </div>

      <div className={LANE_GRID}>
        <div />
        <div className="grid grid-cols-6 border-b border-[color:var(--border)] pb-1">
          {HOUR_TICKS.map((tick) => (
            <span key={tick} className="text-[11px] text-[color:var(--muted-foreground)]">
              {tick}
            </span>
          ))}
        </div>
      </div>

      {lanes.length === 0 ? (
        <p className="py-3 text-[12px] text-[color:var(--muted-foreground)]">
          Nothing has run yet today.
        </p>
      ) : (
        lanes.map((lane) => (
          <div key={lane.automationId} className={LANE_GRID}>
            <div className="truncate text-[12px]">{lane.automationName}</div>
            <div className="relative h-[18px] rounded-md bg-[#FAFAFC]">
              {lane.marks.map((mark) => {
                const line = runSummaryLine({
                  status: mark.status,
                  startedAt: mark.startedAt,
                  durationMs: mark.durationMs,
                });
                return (
                  <button
                    key={mark.runId}
                    type="button"
                    onClick={() => router.push(runHref(mark.automationId, mark.runId))}
                    title={line}
                    aria-label={`${mark.automationName} — ${line}`}
                    style={{ left: `${mark.leftPct}%`, width: `${mark.widthPct}%` }}
                    className={`absolute top-[3px] h-3 rounded transition hover:opacity-70 ${statusDot(mark.status)}`}
                  />
                );
              })}
            </div>
          </div>
        ))
      )}

      <div className="flex flex-wrap items-center gap-4 border-t border-[color:var(--border)] pt-1.5">
        {LEGEND.map((entry) => (
          <div key={entry.status} className="flex items-center gap-1.5">
            <span className={`h-2.5 w-2.5 rounded-[3px] ${statusDot(entry.status)}`} />
            <span className="text-[11px] text-[color:var(--muted-foreground)]">{entry.label}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
