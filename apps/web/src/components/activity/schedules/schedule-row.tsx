'use client';

import Link from 'next/link';
import { Switch } from '@/components/ui/switch';
import {
  dayClockLabel,
  lastResultLabel,
  lastResultTone,
  relativeFuture,
  statusDot,
} from '@/lib/automations/format';
import { capitalize, type ScheduleItem } from '@/lib/automations/types';
import { SCHEDULE_GRID } from './row-model';

/** One scheduled automation: what it is, when it runs, when it goes next, how the last
 *  attempt went, and whether it is on at all.
 *
 *  A failed row is tinted rather than badged — the whole line is the thing that needs
 *  looking at, and a red dot in a column of dots is easy to miss. */
export default function ScheduleRow({
  schedule,
  timezone,
  now,
  failures,
  busy,
  onEdit,
  onToggle,
}: {
  schedule: ScheduleItem;
  timezone: string;
  now: number;
  /** Consecutive failures at the head of this automation's history. */
  failures: number;
  busy: boolean;
  onEdit(schedule: ScheduleItem): void;
  onToggle(schedule: ScheduleItem, enabled: boolean): void;
}) {
  const zone = schedule.timezone ?? timezone ?? undefined;
  const status = schedule.lastRun?.status ?? null;
  const failing = schedule.enabled && status === 'failed';
  const muted = schedule.enabled ? '' : 'text-[color:var(--muted-foreground)]';

  return (
    <div
      className={`${SCHEDULE_GRID} border-b border-[color:var(--border)] last:border-b-0 transition-colors ${
        failing ? 'bg-[rgba(212,24,61,0.05)]' : 'hover:bg-[color:var(--surface-muted)]'
      }`}
    >
      <Link
        href={`/automations/${encodeURIComponent(schedule.automationId)}`}
        className="flex min-w-0 items-center gap-2 rounded-md outline-none focus-visible:ring-3 focus-visible:ring-[color:var(--ring)]/50"
      >
        <span
          aria-hidden
          className={`h-1.5 w-1.5 shrink-0 rounded-full ${
            schedule.enabled
              ? statusDot(status)
              : 'bg-[color:var(--muted-foreground)]/40'
          }`}
        />
        <span className={`truncate text-[13px] font-medium ${muted}`}>{schedule.name}</span>
      </Link>

      <button
        type="button"
        onClick={() => onEdit(schedule)}
        className={`truncate rounded-md text-left text-[13px] outline-none transition-colors hover:text-[color:var(--foreground)] hover:underline focus-visible:ring-3 focus-visible:ring-[color:var(--ring)]/50 ${muted}`}
        title="Change this schedule"
      >
        {capitalize(schedule.triggerSummary)}
      </button>

      {schedule.enabled && schedule.nextRunAt !== null ? (
        <div className="flex flex-col gap-px">
          <span className="text-[13px]">{relativeFuture(schedule.nextRunAt, now)}</span>
          <span className="text-[11px] text-[color:var(--muted-foreground)]">
            {dayClockLabel(schedule.nextRunAt, now, zone)}
          </span>
        </div>
      ) : (
        <span className="text-[13px] text-[color:var(--muted-foreground)]">
          {schedule.enabled ? 'not scheduled' : 'paused'}
        </span>
      )}

      <div
        className={`flex items-center gap-1.5 text-[12px] font-medium ${lastResultTone(
          status,
          schedule.enabled
        )}`}
      >
        <span
          aria-hidden
          className={`h-1.5 w-1.5 shrink-0 rounded-full ${
            schedule.enabled ? statusDot(status) : 'bg-[color:var(--muted-foreground)]/40'
          }`}
        />
        {lastResultLabel(schedule.lastRun, failures)}
      </div>

      <div className="flex justify-end">
        <Switch
          checked={schedule.enabled}
          disabled={busy}
          aria-label={`${schedule.enabled ? 'Pause' : 'Resume'} ${schedule.name}`}
          onCheckedChange={(next) => onToggle(schedule, next)}
        />
      </div>
    </div>
  );
}
