'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { ChevronRight, RotateCcw } from 'lucide-react';
import { automations as automationsApi } from '@/lib/api';
import { formatDuration, startOfDay, timeOfDay } from '@/lib/automations/format';
import { isRunActive, type RunStatus, type RunWithAutomation } from '@/lib/automations/types';
import { triggerPhrase } from './geometry';

const DAY_MS = 86_400_000;

/** Pill colours per status: a tinted ground, the same hue for the text and the dot. */
const PILL: Record<RunStatus, { label: string; tint: string; ink: string }> = {
  failed: { label: 'Failed', tint: 'rgba(212,24,61,0.05)', ink: '#D4183D' },
  succeeded: { label: 'Succeeded', tint: 'rgba(16,163,127,0.08)', ink: '#10A37F' },
  running: { label: 'Running', tint: 'rgba(99,102,241,0.08)', ink: '#6366F1' },
  queued: { label: 'Queued', tint: 'rgba(99,102,241,0.08)', ink: '#6366F1' },
  cancelled: { label: 'Cancelled', tint: '#F7F6FA', ink: '#8A8A95' },
};

/** "today" / "yesterday" / "Thursday" / "3 Sep" — how far back the run is, said the way
 *  a person would say it. */
function dayWord(ms: number, now: number): string {
  const day = startOfDay(ms);
  const today = startOfDay(now);
  if (day === today) return 'today';
  if (day === today - DAY_MS) return 'yesterday';
  if (today - day < 7 * DAY_MS) {
    return new Date(ms).toLocaleDateString(undefined, { weekday: 'long' });
  }
  return new Date(ms).toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
}

const BUTTON = 'inline-flex h-8 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-[10px] px-3 text-[13px] font-medium transition';

/** Breadcrumb, what this run is, how it went, and the two things worth doing about it. */
export default function RunHeader({
  run,
  stoppedAt,
  now,
}: {
  run: RunWithAutomation;
  /** "step 3 of 4", when the run stopped part way. */
  stoppedAt: { position: number; total: number } | null;
  now: number;
}) {
  const router = useRouter();
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);

  const active = isRunActive(run.status);
  const pill = PILL[run.status] ?? PILL.cancelled;
  const at = run.startedAt ?? run.createdAt;

  const meta: string[] = [triggerPhrase(run.trigger)];
  if (active) meta.push('running…');
  else if (run.durationMs != null) meta.push(`Took ${formatDuration(run.durationMs)}`);
  if (stoppedAt) meta.push(`Stopped at step ${stoppedAt.position} of ${stoppedAt.total}`);
  if (run.versionNumber != null) meta.push(`Version ${run.versionNumber}`);

  const runAgain = async () => {
    setStarting(true);
    setStartError(null);
    try {
      const { runId } = await automationsApi.startRun(run.automationId, 'manual');
      router.push(`/activity/runs/${encodeURIComponent(runId)}`);
    } catch (reason) {
      setStarting(false);
      setStartError(reason instanceof Error ? reason.message : 'Could not start a new run.');
    }
  };

  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex items-center gap-1.5 text-[12px] text-[color:var(--muted-foreground)]">
        <Link href="/activity" className="hover:text-[color:var(--foreground)]">
          Activity
        </Link>
        <ChevronRight size={12} strokeWidth={2} className="shrink-0" />
        <span className="truncate">{run.automationName}</span>
      </div>

      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 flex-col gap-2">
          <div className="flex flex-wrap items-center gap-2.5">
            <span
              className="inline-flex h-6 items-center gap-1.5 rounded-full px-2.5 text-[12px] font-medium"
              style={{ background: pill.tint, color: pill.ink }}
            >
              <span
                className={`inline-block h-1.5 w-1.5 rounded-full ${active ? 'animate-pulse' : ''}`}
                style={{ background: pill.ink }}
              />
              {pill.label}
            </span>
            <h1 className="text-[20px] font-semibold leading-7 tracking-[-0.02em]">
              Run of {dayWord(at, now)}, {timeOfDay(at)}
            </h1>
          </div>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-[color:var(--muted-foreground)]">
            {meta.map((part, i) => (
              <span key={part} className="flex items-center gap-3">
                {i > 0 && <span aria-hidden>·</span>}
                {part}
              </span>
            ))}
          </div>
        </div>

        <div className="flex shrink-0 flex-col items-end gap-1.5">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={runAgain}
              disabled={starting}
              className={`${BUTTON} border border-[color:var(--border)] hover:bg-[color:var(--surface-muted)] disabled:opacity-50`}
            >
              <RotateCcw size={14} strokeWidth={2} />
              {starting ? 'Starting…' : 'Run again'}
            </button>
            <Link
              href={`/automations/${encodeURIComponent(run.automationId)}`}
              className={`${BUTTON} bg-[color:var(--primary)] px-3 text-[color:var(--primary-foreground)] hover:opacity-90`}
            >
              Open the automation
            </Link>
          </div>
          {startError && (
            <p className="max-w-[280px] text-right text-[11px] text-[#D4183D]">{startError}</p>
          )}
        </div>
      </div>
    </div>
  );
}
