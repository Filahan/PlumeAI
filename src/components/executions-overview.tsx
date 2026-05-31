'use client';

import { Task } from '@/lib/types';

const MAX_SQUARES = 20;

function statusClass(status: 'succeeded' | 'failed' | 'cancelled'): string {
  if (status === 'succeeded') return 'bg-[#10A37F]';
  if (status === 'failed') return 'bg-[#D4183D]';
  return 'bg-gray-300';
}

function relativeTime(ms: number): string {
  const diff = Date.now() - ms;
  if (diff < 60_000) return 'just now';
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
  return `${Math.floor(diff / 86_400_000)}d ago`;
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60_000).toFixed(1)}m`;
}

export default function ExecutionsOverview({
  tasks, onSelect,
}: {
  tasks: Task[];
  onSelect: (id: string) => void;
}) {
  // Only surface tasks that have actually been executed (or are running).
  const withRuns = tasks.filter((t) => (t.runs ?? []).length > 0 || t.status === 'running');
  if (withRuns.length === 0) return null;

  // Sort by most recent activity first.
  const sorted = [...withRuns].sort((a, b) => {
    const aTime = a.runs?.[a.runs.length - 1]?.endedAt ?? a.updatedAt;
    const bTime = b.runs?.[b.runs.length - 1]?.endedAt ?? b.updatedAt;
    return bTime - aTime;
  });

  return (
    <div className="rounded-2xl border border-[color:var(--border)] bg-white max-h-[200px] overflow-y-auto divide-y divide-[color:var(--border)]">
      {sorted.map((t) => {
        const recent = (t.runs ?? []).slice(-MAX_SQUARES);
        const last = recent[recent.length - 1];
        const isRunning = t.status === 'running';
        return (
          <button
            key={t.id}
            type="button"
            onClick={() => onSelect(t.id)}
            className="w-full flex items-center gap-3 px-4 py-2 text-left transition hover:bg-[color:var(--surface-muted)]/60"
          >
            <div className="flex items-center gap-[3px] flex-1 min-w-0 flex-wrap">
              {recent.map((r, i) => (
                <span
                  key={i}
                  title={`${new Date(r.startedAt).toLocaleString()} — ${r.status} (${formatDuration(r.durationMs)})${r.error ? `\n${r.error}` : ''}`}
                  className={`w-3 h-3 rounded-[3px] ${statusClass(r.status)}`}
                />
              ))}
              {isRunning && (
                <span
                  title="Running…"
                  className="w-3 h-3 rounded-[3px] bg-[#6366f1] animate-pulse"
                />
              )}
            </div>
            <span className="shrink-0 text-[11px] text-[color:var(--muted-foreground)] tabular-nums">
              {isRunning ? 'running…' : last ? relativeTime(last.endedAt) : '—'}
            </span>
          </button>
        );
      })}
    </div>
  );
}
