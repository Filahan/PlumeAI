'use client';

import Link from 'next/link';
import { AlertTriangle } from 'lucide-react';
import { runHref, type FailingStreak } from '@/lib/activity/derive';
import { runMoment, startOfDay, timeOfDay } from '@/lib/automations/format';

/** When the failures began, at the precision that is useful: a clock time while it is
 *  still today, the full moment once it is not. */
function sinceLabel(since: number): string {
  return startOfDay(since) === startOfDay(Date.now()) ? timeOfDay(since) : runMoment(since);
}

function detailLine(streak: FailingStreak, stepName: string | null): string {
  const since = sinceLabel(streak.since);
  if (stepName) return `Since ${since} — every attempt stops on “${stepName}”.`;
  if (streak.stoppedByStepId) return `Since ${since} — every attempt stops on the same step.`;
  return `Since ${since} — the attempts stop at different steps.`;
}

/** The one thing on the page that asks for a decision: an automation that has failed
 *  more than once in a row, named, with the way in to the failure that matters most. */
export default function AttentionBanner({
  streak,
  stepName,
}: {
  streak: FailingStreak;
  stepName: string | null;
}) {
  return (
    <section className="flex items-center gap-3 rounded-[14px] border border-[rgba(212,24,61,0.30)] bg-[rgba(212,24,61,0.05)] px-4 py-3">
      <AlertTriangle size={16} strokeWidth={2} className="shrink-0 text-[#D4183D]" />
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <p className="text-[13px] font-medium leading-[18px] text-[#D4183D]">
          {streak.automationName} has failed {streak.count} times in a row
        </p>
        <p className="text-[12px] leading-4 text-[color:var(--muted-foreground)]">
          {detailLine(streak, stepName)}
        </p>
      </div>
      <Link
        href={runHref(streak.automationId, streak.latestRun.id)}
        className="inline-flex h-8 shrink-0 items-center whitespace-nowrap rounded-[10px] bg-[color:var(--primary)] px-3 text-[13px] font-medium text-white transition hover:opacity-90"
      >
        See what happened
      </Link>
    </section>
  );
}
