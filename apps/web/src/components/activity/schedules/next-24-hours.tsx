'use client';

import { useMemo } from 'react';
import {
  collisions,
  HORIZON_MS,
  joinNames,
  markLeftPct,
  namesIn,
  plannedRuns,
  planStride,
} from '@/lib/activity/plan';
import { zonedClock } from '@/lib/automations/format';
import type { ScheduleItem } from '@/lib/automations/types';

/** Collision labels crowd each other; three is as many as the strip can say out loud. */
const MAX_LABELS = 3;

/** What is due between now and this time tomorrow, as one line.
 *
 *  The marks are computed in the browser from each schedule's own shape (see
 *  `lib/activity/plan.ts`) — `/schedules` only reports the *next* run, and a plan that
 *  stops after one mark per automation is not a plan. */
export default function Next24Hours({
  schedules,
  timezone,
  now,
}: {
  schedules: ScheduleItem[];
  /** The workspace zone; `''` before the first load. */
  timezone: string;
  now: number;
}) {
  const zone = timezone || undefined;

  const runs = useMemo(
    () => plannedRuns(schedules, now, HORIZON_MS, zone),
    [schedules, now, zone]
  );
  const groups = useMemo(() => collisions(runs), [runs]);
  const colliding = useMemo(
    () => new Set(groups.flatMap((group) => group.runs.map((run) => run.at))),
    [groups]
  );
  const thinned = useMemo(
    () =>
      schedules
        .map((schedule) => ({ schedule, stride: planStride(schedule, now) }))
        .filter((entry) => entry.stride > 1),
    [schedules, now]
  );

  const first = groups[0];

  return (
    <section className="flex flex-col gap-2.5 rounded-2xl border border-[color:var(--border)] bg-white px-5 pb-[18px] pt-4">
      <div className="flex items-baseline justify-between gap-4">
        <h2 className="text-[13px] font-medium">The next 24 hours</h2>
        <span className="text-[12px] text-[color:var(--muted-foreground)]">
          Each mark is one planned run
        </span>
      </div>

      <div
        role="img"
        aria-label={
          runs.length === 0
            ? 'Nothing is planned in the next 24 hours'
            : `${runs.length} runs planned in the next 24 hours`
        }
        className="relative h-11"
      >
        <div className="absolute inset-x-0 top-5 h-0.5 rounded-sm bg-[color:var(--border)]" />
        <div className="absolute left-0 top-[14px] h-[14px] w-0.5 rounded-sm bg-[color:var(--foreground)]" />
        <div className="absolute left-0 top-8 text-[11px] text-[color:var(--foreground)]">now</div>
        <div className="absolute right-0 top-8 text-[11px] text-[color:var(--muted-foreground)]">
          in 24 h
        </div>

        {/* Inset by a mark's width so nothing at the far end hangs off the track. */}
        <div className="absolute inset-y-0 left-0 right-[10px]">
          {runs
            .filter((run) => !colliding.has(run.at))
            .map((run) => (
              <span
                key={`${run.automationId}-${run.at}`}
                aria-hidden
                title={`${run.name} · ${zonedClock(run.at, zone)}`}
                className="absolute top-[15px] h-2.5 w-2.5 rounded-[3px] bg-[color:var(--muted-foreground)]"
                style={{ left: `${markLeftPct(run.at, now)}%` }}
              />
            ))}

          {groups.map((group, index) => {
            const left = markLeftPct(group.at, now);
            return (
              <span key={group.at} aria-hidden>
                <span
                  className="absolute top-2 h-6 w-[3px] rounded-sm bg-[color:var(--primary)]"
                  style={{ left: `${left}%` }}
                />
                {index < MAX_LABELS && (
                  <span
                    className="absolute top-8 -translate-x-1/2 whitespace-nowrap text-[11px] text-[color:var(--primary)]"
                    style={{ left: `${left}%` }}
                  >
                    {zonedClock(group.at, zone)} · {group.runs.length} runs
                  </span>
                )}
              </span>
            );
          })}
        </div>
      </div>

      {runs.length === 0 ? (
        <p className="text-[12px] text-[color:var(--muted-foreground)]">
          Nothing is due in the next 24 hours.
        </p>
      ) : (
        first && (
          <p className="text-[12px] text-[color:var(--muted-foreground)]">
            At {zonedClock(first.at, zone)} {joinNames(namesIn(first.runs))}{' '}
            {first.runs.length > 2 ? 'are all due' : 'are both due'}. They run one after the
            other, so the later ones start a few seconds late.
            {groups.length > 1 && ` ${groups.length - 1} more overlap like this today.`}
          </p>
        )
      )}

      {thinned.map(({ schedule, stride }) => (
        <p key={schedule.automationId} className="text-[12px] text-[color:var(--muted-foreground)]">
          {schedule.name} runs every {schedule.everyMinutes}{' '}
          {schedule.everyMinutes === 1 ? 'minute' : 'minutes'} — too often to draw, so one mark
          here stands for {stride} runs.
        </p>
      ))}
    </section>
  );
}
