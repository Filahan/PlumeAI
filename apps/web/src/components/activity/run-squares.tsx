'use client';

import { useRouter } from 'next/navigation';
import { MAX_SQUARES, runHref } from '@/lib/activity/derive';
import { runSummaryLine, statusDot } from '@/lib/automations/format';
import type { RunListItem } from '@/lib/automations/types';

/** One automation's recent history, oldest on the left so the newest square is always
 *  the rightmost one — the same reading direction as the timeline below the grid.
 *
 *  `runs` arrives newest first (the order the feed and `runsByAutomation` use); the strip
 *  takes the most recent `MAX_SQUARES` of it and turns it around. Every square is a real
 *  button: it navigates, so it has to be reachable by keyboard and named out loud. */
export default function RunSquares({
  automationName,
  runs,
}: {
  automationName: string;
  runs: RunListItem[];
}) {
  const router = useRouter();
  const recent = runs.slice(0, MAX_SQUARES).reverse();

  if (recent.length === 0) {
    return <span className="text-[12px] text-[color:var(--muted-foreground)]">No runs yet</span>;
  }

  return (
    <div className="flex items-center gap-[3px]">
      {recent.map((run) => {
        const line = runSummaryLine(run);
        return (
          <button
            key={run.id}
            type="button"
            onClick={() => router.push(runHref(run.automationId, run.id))}
            title={`${line}${run.error ? `\n${run.error}` : ''}`}
            aria-label={`${automationName} — ${line}`}
            className={`h-3 w-3 shrink-0 rounded-[3px] transition hover:opacity-70 ${statusDot(run.status)}`}
          />
        );
      })}
    </div>
  );
}
