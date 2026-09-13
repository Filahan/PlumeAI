'use client';

import RunSquares from '@/components/activity/run-squares';
import { nextRunLabel, statusDot } from '@/lib/automations/format';
import {
  capitalize,
  isRunActive,
  type AutomationSummary,
  type RunListItem,
} from '@/lib/automations/types';

/** The one grid every row and the header share, so the four columns stay aligned. */
const ROW_GRID =
  'grid grid-cols-[minmax(0,1fr)_150px_320px_130px] items-center gap-4 px-4 py-[9px]';

const CELL = 'text-[12px] text-[color:var(--muted-foreground)] truncate';

/** The backend's phrase for "no schedule". Anything else is a real trigger summary. */
const MANUAL_SUMMARY = 'manual trigger';

function scheduleLabel(automation: AutomationSummary): string {
  const summary = automation.triggerSummary;
  const phrase = !summary || summary === MANUAL_SUMMARY ? 'By hand only' : capitalize(summary);
  return automation.enabled ? phrase : `${phrase} · paused`;
}

/** One automation, one line, four columns: what it is, when it runs, how it has been
 *  going, and when it goes next. */
function Row({
  automation,
  runs,
  failing,
}: {
  automation: AutomationSummary;
  runs: RunListItem[];
  failing: boolean;
}) {
  const latest = runs[0];
  const status = latest?.status ?? automation.lastRun?.status ?? null;
  const running = latest ? isRunActive(latest.status) : false;

  return (
    <div
      className={`${ROW_GRID} border-b border-[color:var(--border)] last:border-b-0 transition-colors ${
        failing ? 'bg-[rgba(212,24,61,0.05)]' : 'hover:bg-[color:var(--surface-muted)]'
      }`}
    >
      <div className="flex min-w-0 items-center gap-2">
        <span
          className={`h-1.5 w-1.5 shrink-0 rounded-full ${
            automation.enabled ? statusDot(status) : 'bg-[color:var(--muted-foreground)]/40'
          }`}
        />
        <span className="truncate text-[13px] font-medium leading-[18px]">{automation.name}</span>
      </div>

      <div className={CELL}>{scheduleLabel(automation)}</div>

      <RunSquares automationName={automation.name} runs={runs} />

      {running ? (
        <div className="truncate text-[12px] font-medium text-[color:var(--foreground)]">
          running now
        </div>
      ) : (
        <div className={CELL}>
          {automation.enabled ? nextRunLabel(automation.nextRunAt) : 'paused'}
        </div>
      )}
    </div>
  );
}

/** Every automation you have, with its recent history — the heart of the Runs tab.
 *
 *  The rows come from `/automations`, not from the run feed, so an automation that has
 *  never run still has a line (and an empty strip) instead of vanishing. */
export default function RunsGrid({
  automations,
  byAutomation,
  failingId,
}: {
  automations: AutomationSummary[];
  byAutomation: Map<string, RunListItem[]>;
  failingId?: string | null;
}) {
  return (
    <div className="overflow-hidden rounded-2xl border border-[color:var(--border)] bg-white">
      <div
        className={`${ROW_GRID} border-b border-[color:var(--border)] bg-[#FAFAFC] text-[11px] font-semibold uppercase tracking-[0.08em] text-[color:var(--muted-foreground)]`}
      >
        <div>Automation</div>
        <div>Schedule</div>
        <div>Recent runs</div>
        <div>Next run</div>
      </div>

      {automations.map((automation) => (
        <Row
          key={automation.id}
          automation={automation}
          runs={byAutomation.get(automation.id) ?? []}
          failing={automation.id === failingId}
        />
      ))}
    </div>
  );
}
