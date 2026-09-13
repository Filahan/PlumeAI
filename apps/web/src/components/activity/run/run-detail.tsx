'use client';

import { useMemo, useState } from 'react';
import Link from 'next/link';
import { Workflow } from 'lucide-react';
import ActivityShell from '@/components/activity/activity-shell';
import EmptyState from '@/components/activity/empty-state';
import RunErrorCard from './run-error-card';
import RunGantt from './run-gantt';
import RunHeader from './run-header';
import StepPanels from './step-panels';
import { defaultLaneId, failedLane, runGeometry } from './geometry';
import { useRun } from './use-run';

const BACK = (
  <Link
    href="/activity"
    className="inline-flex h-9 items-center rounded-full bg-[color:var(--primary)] px-4 text-[13px] font-medium text-[color:var(--primary-foreground)] transition hover:opacity-90"
  >
    Back to Activity
  </Link>
);

/** One run, end to end: what it was, why it stopped, how its time was spent, and what
 *  the step you are looking at sent and got back.
 *
 *  The selection is held here rather than in the gantt because two things read it — the
 *  highlighted lane and the panels — and `null` means "whatever the run says matters
 *  most", so a run that is still going can move its own default from step to step until
 *  the moment someone clicks. */
export default function RunDetail({ runId }: { runId: string }) {
  const { run, loading, notFound, error, now } = useRun(runId);
  const [picked, setPicked] = useState<string | null>(null);

  const geometry = useMemo(() => (run ? runGeometry(run, now) : null), [run, now]);

  if (loading) {
    return (
      <ActivityShell title="Activity" subtitle="Loading this run…">
        <div className="h-[360px]" />
      </ActivityShell>
    );
  }

  if (notFound || (!run && !error)) {
    return (
      <ActivityShell title="Activity" subtitle="One run, step by step.">
        <EmptyState
          icon={<Workflow size={20} strokeWidth={1.75} />}
          title="This run no longer exists"
          description="Runs are kept for the last 200 of each automation, so an old one eventually makes way. Nothing is wrong."
          action={BACK}
        />
      </ActivityShell>
    );
  }

  if (!run || !geometry) {
    return (
      <ActivityShell title="Activity" subtitle="One run, step by step.">
        <EmptyState
          icon={<Workflow size={20} strokeWidth={1.75} />}
          title="This run is not available right now"
          description={error ?? 'Could not load this run.'}
          action={BACK}
        />
      </ActivityShell>
    );
  }

  const stopped = failedLane(geometry.lanes, run.stoppedByStepId);
  // `picked` outlives a navigation to another run of the same automation — which is the
  // point, the step you were reading stays the step you are reading — but a step id that
  // is not in *this* run falls back to whatever this run says matters most.
  const fallbackId = defaultLaneId(geometry.lanes, run.stoppedByStepId);
  const selected =
    geometry.lanes.find((lane) => lane.step.stepId === picked) ??
    geometry.lanes.find((lane) => lane.step.stepId === fallbackId) ??
    geometry.lanes[0] ??
    null;

  return (
    <ActivityShell
      header={
        <RunHeader
          run={run}
          stoppedAt={
            run.status === 'failed' && stopped
              ? { position: stopped.position, total: geometry.lanes.length }
              : null
          }
          now={now}
        />
      }
    >
      {run.status === 'failed' && (
        <RunErrorCard step={stopped?.step ?? null} error={run.error} />
      )}

      {geometry.lanes.length === 0 ? (
        <EmptyState
          title="This run has no steps"
          description="The automation had nothing to do when this run started."
        />
      ) : (
        <>
          <RunGantt
            geometry={geometry}
            selectedStepId={selected?.step.stepId ?? null}
            onSelect={setPicked}
          />
          {selected && <StepPanels lane={selected} automationId={run.automationId} />}
        </>
      )}
    </ActivityShell>
  );
}
