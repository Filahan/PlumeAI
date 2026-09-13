'use client';

import { formatDuration } from '@/lib/automations/format';
import type { RunStepStatus } from '@/lib/automations/types';
import { retryPolicyLine, type RunGeometry, type StepLane } from './geometry';

/** The three columns every row shares, so the bars line up under the ruler. */
const ROW = 'grid grid-cols-[260px_minmax(0,1fr)_90px] items-center gap-4 px-4';

/** The dashes that stand for a backoff wait. Same recipe in the lane and the legend, so
 *  the key below is literally the thing it explains. */
const DASHES =
  'repeating-linear-gradient(to right, rgba(212,24,61,0.35) 0 4px, transparent 4px 8px)';

/** Bar colour by step status — the dot's colours, as solid fills. */
const BAR: Record<string, string> = {
  succeeded: '#10A37F',
  failed: '#D4183D',
  running: '#6366F1',
  skipped: 'rgba(138,138,149,0.4)',
  cancelled: 'rgba(138,138,149,0.4)',
  pending: 'rgba(138,138,149,0.4)',
};

function dotColor(status: RunStepStatus): string {
  return BAR[status] ?? 'rgba(138,138,149,0.4)';
}

/** One step's track: a bar per attempt, dashes for the waits in between. */
function Track({ lane }: { lane: StepLane }) {
  if (!lane.ran) {
    return (
      <div className="relative h-4 rounded-[5px] bg-[#FAFAFC]">
        <span className="absolute left-3 text-[11px] leading-4 text-[color:var(--muted-foreground)]">
          never ran
        </span>
      </div>
    );
  }

  const fill = dotColor(lane.step.status);

  return (
    <div className="relative h-4 rounded-[5px] bg-[#FAFAFC]">
      {lane.waits.map((wait, i) =>
        wait.widthPct > 0 ? (
          <span
            key={`wait-${i}`}
            className="absolute top-[7px] h-[2px]"
            style={{ left: `${wait.leftPct}%`, width: `${wait.widthPct}%`, background: DASHES }}
          />
        ) : null
      )}
      {lane.segments.map((segment) => (
        <span
          key={segment.n}
          title={
            lane.estimated
              ? `Try ${segment.n} — about ${formatDuration(Math.round(segment.durationMs))}`
              : formatDuration(Math.round(segment.durationMs))
          }
          className={`absolute top-[2px] h-3 rounded-[4px] ${
            lane.step.status === 'running' ? 'animate-pulse' : ''
          }`}
          style={{
            left: `${segment.leftPct}%`,
            width: `${segment.widthPct}%`,
            background: segment.failed ? '#D4183D' : fill,
          }}
        />
      ))}
    </div>
  );
}

/** The run as a timeline: one lane per step, one bar per attempt, the dashed waits in
 *  between. Everything is placed in percentages of the run's own duration, so the whole
 *  thing reflows with the window and never needs a measured width. */
export default function RunGantt({
  geometry,
  selectedStepId,
  onSelect,
}: {
  geometry: RunGeometry;
  selectedStepId: string | null;
  onSelect: (stepId: string) => void;
}) {
  return (
    <section className="flex flex-col overflow-hidden rounded-2xl border border-[color:var(--border)] bg-white">
      <div
        className={`${ROW} border-b border-[color:var(--border)] bg-[#FAFAFC] py-2.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-[color:var(--muted-foreground)]`}
      >
        <div>Step</div>
        <div>0s — {formatDuration(geometry.totalMs)}</div>
        <div className="text-right">Took</div>
      </div>

      {geometry.lanes.map((lane) => {
        const selected = lane.step.stepId === selectedStepId;
        const failed = lane.step.status === 'failed';
        return (
          <button
            key={lane.step.id}
            type="button"
            onClick={() => onSelect(lane.step.stepId)}
            aria-pressed={selected}
            className={`${ROW} w-full border-b border-[color:var(--border)] py-[9px] text-left transition-colors last:border-b-0 ${
              failed ? 'bg-[rgba(212,24,61,0.05)]' : ''
            } ${selected ? 'ring-1 ring-inset ring-[color:var(--border)]' : ''} hover:bg-[color:var(--surface-muted)]`}
          >
            <div className="flex min-w-0 items-center gap-2">
              <span
                className="h-1.5 w-1.5 shrink-0 rounded-full"
                style={{ background: dotColor(lane.step.status) }}
              />
              <span
                className={`truncate text-[13px] ${failed ? 'font-medium' : ''} ${
                  lane.ran ? '' : 'text-[color:var(--muted-foreground)]'
                }`}
              >
                {lane.step.name}
              </span>
              {lane.attempts > 1 && (
                <span className="shrink-0 rounded-full border border-[rgba(212,24,61,0.30)] px-1.5 py-px text-[11px] text-[color:var(--muted-foreground)]">
                  {lane.attempts} tries
                </span>
              )}
            </div>

            <Track lane={lane} />

            <div
              className={`text-right text-[12px] tabular-nums ${
                failed ? 'text-[#D4183D]' : 'text-[color:var(--muted-foreground)]'
              }`}
            >
              {lane.step.durationMs != null ? formatDuration(lane.step.durationMs) : '—'}
            </div>
          </button>
        );
      })}

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-[color:var(--border)] bg-[#FAFAFC] px-4 py-2">
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-[2px] w-4" style={{ background: DASHES }} />
          <span className="text-[11px] text-[color:var(--muted-foreground)]">
            waiting before trying again
          </span>
        </span>
        <span className="text-[11px] text-[color:var(--muted-foreground)]">
          {retryPolicyLine(geometry.backoffSeconds)}
        </span>
      </div>
    </section>
  );
}
