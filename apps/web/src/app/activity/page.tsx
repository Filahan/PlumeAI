'use client';

import { useState } from 'react';
import Link from 'next/link';
import { Workflow } from 'lucide-react';
import ActivityShell from '@/components/activity/activity-shell';
import AttentionBanner from '@/components/activity/attention-banner';
import DayTimeline from '@/components/activity/day-timeline';
import EmptyState from '@/components/activity/empty-state';
import RangeTabs from '@/components/activity/range-tabs';
import RunsGrid from '@/components/activity/runs-grid';
import type { ActivityRange } from '@/lib/activity/derive';
import { useActivity } from '@/lib/activity/use-activity';

/** Runs tab: every automation's recent history in one grid, plus today hour by hour.
 *
 *  Three failure modes, three different calms — nothing here throws:
 *    - the automations list is down: one empty state, no grid;
 *    - there are no automations yet: the same empty state, pointing at how to make one;
 *    - only the run feed is down (it is deployed separately): the grid still lists every
 *      automation, the squares are simply empty and the timeline says why.
 */
export default function ActivityRunsPage() {
  const [range, setRange] = useState<ActivityRange>('7d');
  const { automations, byAutomation, streak, streakStepName, lanes, loading, error, runsError } =
    useActivity(range);

  const firstLoad = loading && automations.length === 0;

  return (
    <ActivityShell
      title="Activity"
      subtitle="Newest run on the right. Click any square to open that run."
      actions={<RangeTabs value={range} onChange={setRange} />}
    >
      {streak && <AttentionBanner streak={streak} stepName={streakStepName} />}

      {firstLoad ? (
        <div className="h-[360px]" />
      ) : error ? (
        <EmptyState
          icon={<Workflow size={20} strokeWidth={1.75} />}
          title="Activity is not available right now"
          description={error}
        />
      ) : automations.length === 0 ? (
        <EmptyState
          icon={<Workflow size={20} strokeWidth={1.75} />}
          title="No automations yet"
          description="Once you build an automation, every run it makes shows up here as a square."
          action={
            <Link
              href="/"
              className="inline-flex h-9 items-center rounded-full bg-[color:var(--primary)] px-4 text-[13px] font-medium text-white transition hover:opacity-90"
            >
              Build an automation
            </Link>
          }
        />
      ) : (
        <>
          <RunsGrid
            automations={automations}
            byAutomation={byAutomation}
            failingId={streak?.automationId ?? null}
          />
          {runsError ? (
            <EmptyState title="Run history is not available yet" description={runsError} />
          ) : (
            <DayTimeline lanes={lanes} />
          )}
        </>
      )}
    </ActivityShell>
  );
}
