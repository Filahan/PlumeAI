'use client';

import type { RunSummary } from '@/lib/automations/types';
import { formatDuration, relativePast } from '@/lib/automations/format';

const MAX_SQUARES = 20;

function statusClass(status: RunSummary['status']): string {
  if (status === 'succeeded') return 'bg-[#10A37F]';
  if (status === 'failed') return 'bg-[#D4183D]';
  if (status === 'running') return 'bg-[#6366f1] animate-pulse';
  if (status === 'queued') return 'bg-[#f59e0b]';
  return 'bg-gray-300'; // cancelled
}

/** Airflow-style run-history strip for a single automation. */
export default function ExecutionsOverview({
  runs, onSelectRun,
}: {
  runs: RunSummary[];
  onSelectRun?: (runId: string) => void;
}) {
  if (runs.length === 0) return null;
  const recent = runs.slice(0, MAX_SQUARES).slice().reverse();
  const last = runs[0];

  return (
    <div className="rounded-2xl border border-[color:var(--border)] bg-white px-4 py-2.5 flex items-center gap-3">
      <div className="flex items-center gap-[3px] flex-1 min-w-0 flex-wrap">
        {recent.map((r) => (
          <button
            key={r.id}
            type="button"
            onClick={() => onSelectRun?.(r.id)}
            title={`${r.startedAt ? new Date(r.startedAt).toLocaleString() : 'not started'} — ${r.status}${
              r.durationMs != null ? ` (${formatDuration(r.durationMs)})` : ''
            }${r.error ? `\n${r.error}` : ''}`}
            className={`w-3 h-3 rounded-[3px] ${statusClass(r.status)}`}
          />
        ))}
      </div>
      <span className="shrink-0 text-[11px] text-[color:var(--muted-foreground)] tabular-nums">
        {last.status === 'running' || last.status === 'queued'
          ? `${last.status}…`
          : last.endedAt
            ? relativePast(last.endedAt)
            : '—'}
      </span>
    </div>
  );
}
