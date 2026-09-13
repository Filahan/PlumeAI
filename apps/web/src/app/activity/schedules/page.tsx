'use client';

import Link from 'next/link';
import { CalendarClock, Clock } from 'lucide-react';
import ActivityShell from '@/components/activity/activity-shell';
import EmptyState from '@/components/activity/empty-state';
import Next24Hours from '@/components/activity/schedules/next-24-hours';
import PauseEverythingButton from '@/components/activity/schedules/pause-everything-button';
import SchedulesTable from '@/components/activity/schedules/schedules-table';
import { useSchedules } from '@/components/activity/schedules/use-schedules';

/** Schedules: what is due, and when.
 *
 *  Two things, in the order you ask them in: the next 24 hours as one line, then every
 *  schedule as a row you can switch off. An account with nothing scheduled — which is
 *  every new account — gets a sentence saying so rather than an empty grid. */
export default function ActivitySchedulesPage() {
  const { schedules, timezone, failures, now, loading, error, busy, reload, setEnabled } =
    useSchedules();

  const firstLoad = loading && timezone === '';
  const allPaused = schedules.length > 0 && schedules.every((schedule) => !schedule.enabled);

  return (
    <ActivityShell
      title="Schedules"
      subtitle={
        timezone
          ? `What is due, and when. Times are shown in ${timezone}.`
          : 'What is due, and when.'
      }
      actions={
        schedules.length > 0 ? (
          <PauseEverythingButton
            allPaused={allPaused}
            busy={busy}
            onConfirm={(enabled) => void setEnabled(null, enabled)}
          />
        ) : undefined
      }
    >
      {firstLoad ? (
        <div className="h-[360px]" />
      ) : error ? (
        <EmptyState
          icon={<CalendarClock size={20} strokeWidth={1.75} />}
          title="Schedules are not available right now"
          description={error}
        />
      ) : schedules.length === 0 ? (
        <EmptyState
          icon={<CalendarClock size={20} strokeWidth={1.75} />}
          title="Nothing is on a schedule"
          description="Every automation you have runs by hand, when you press Run. Give one a schedule and it will show up here with its next few runs."
          action={
            <Link
              href="/"
              className="inline-flex h-9 items-center rounded-full bg-[color:var(--primary)] px-4 text-[13px] font-medium text-[color:var(--primary-foreground)] transition hover:opacity-90"
            >
              Open your automations
            </Link>
          }
        />
      ) : (
        <>
          <Next24Hours schedules={schedules} timezone={timezone} now={now} />
          <SchedulesTable
            schedules={schedules}
            timezone={timezone}
            now={now}
            failures={failures}
            busy={busy}
            onToggle={(schedule, enabled) => void setEnabled([schedule.automationId], enabled)}
            onSaved={reload}
          />
          <p className="flex items-center gap-2 text-[12px] text-[color:var(--muted-foreground)]">
            <Clock size={14} strokeWidth={1.75} aria-hidden className="shrink-0" />
            A paused automation keeps its schedule and can still be run by hand. Nothing is lost.
          </p>
        </>
      )}
    </ActivityShell>
  );
}
