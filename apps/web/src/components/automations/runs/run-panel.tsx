'use client';

import { AlertCircle, ChevronDown, X } from 'lucide-react';
import { useAutomationsStore, useEditorRuns } from '@/lib/automations/store';
import { formatDuration, relativePast, statusDot } from '@/lib/automations/format';
import ExecutionsOverview from '@/components/executions-overview';
import RunStepRow from '@/components/automations/runs/run-step-row';

/** Bottom drawer of the editor: run history on the left, the selected run's steps on
 *  the right. Everything comes from the store, including the live updates of whichever
 *  run is streaming.
 *
 *  This is the one container that *should* re-render on every `step_text` delta, so it
 *  selects `activeRun` deliberately — and nothing else from `current`, so the rest of
 *  the editor stays still. */
export default function RunPanel() {
  const open = useAutomationsStore((s) => s.current?.runPanelOpen ?? false);
  const runs = useEditorRuns();
  const activeRunId = useAutomationsStore((s) => s.current?.activeRunId ?? null);
  const activeRun = useAutomationsStore((s) => s.current?.activeRun ?? null);
  const selectRun = useAutomationsStore((s) => s.selectRun);
  const setRunPanelOpen = useAutomationsStore((s) => s.setRunPanelOpen);
  if (!open) return null;

  return (
    <section className="h-[280px] shrink-0 border-t border-[color:var(--border)] bg-[color:var(--surface-muted)]/40 flex flex-col">
      <header className="shrink-0 flex items-center gap-3 px-4 py-2 border-b border-[color:var(--border)]">
        <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-[color:var(--muted-foreground)] shrink-0">
          Runs
        </span>
        <div className="flex-1 min-w-0">
          <ExecutionsOverview runs={runs} onSelectRun={(id) => void selectRun(id)} />
        </div>
        <button
          type="button"
          onClick={() => setRunPanelOpen(false)}
          aria-label="Hide runs"
          className="h-7 w-7 shrink-0 inline-flex items-center justify-center rounded-md text-[color:var(--muted-foreground)] hover:bg-white hover:text-[color:var(--foreground)] transition"
        >
          <ChevronDown size={14} strokeWidth={2} />
        </button>
      </header>

      <div className="flex-1 min-h-0 grid grid-cols-[220px_1fr]">
        <div className="overflow-y-auto border-r border-[color:var(--border)] p-2 space-y-1">
          {runs.length === 0 ? (
            <p className="px-2 py-1.5 text-[12px] text-[color:var(--muted-foreground)]">
              No runs yet
            </p>
          ) : (
            runs.map((r) => (
              <button
                key={r.id}
                type="button"
                onClick={() => void selectRun(r.id)}
                className={`w-full text-left rounded-lg px-2.5 py-2 text-[12px] transition ${
                  r.id === activeRunId ? 'bg-white shadow-[0_1px_2px_rgba(0,0,0,0.04)]' : 'hover:bg-white/60'
                }`}
              >
                <div className="flex items-center gap-1.5">
                  <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${statusDot(r.status)}`} />
                  <span className="font-medium capitalize truncate">{r.status}</span>
                  <span className="ml-auto text-[10px] uppercase text-[color:var(--muted-foreground)] shrink-0">
                    {r.trigger}
                  </span>
                </div>
                <div className="mt-0.5 text-[11px] text-[color:var(--muted-foreground)] tabular-nums">
                  {r.startedAt ? relativePast(r.startedAt) : 'queued'}
                  {r.durationMs != null && ` · ${formatDuration(r.durationMs)}`}
                </div>
              </button>
            ))
          )}
        </div>

        <div className="overflow-y-auto p-3 space-y-2">
          {!activeRunId ? (
            <p className="text-[12px] text-[color:var(--muted-foreground)]">
              Select a run to see its steps.
            </p>
          ) : !activeRun ? (
            <p className="text-[12px] text-[color:var(--muted-foreground)]">Loading run…</p>
          ) : (
            <>
              {activeRun.error && (
                <p className="flex items-start gap-1.5 text-[12px] text-[#D4183D]">
                  <AlertCircle size={13} strokeWidth={2} className="mt-0.5 shrink-0" />
                  <span className="break-words">{activeRun.error}</span>
                </p>
              )}
              {activeRun.stoppedByStepId && (
                <p className="flex items-center gap-1.5 text-[11px] text-[color:var(--muted-foreground)]">
                  <X size={12} strokeWidth={2} />
                  Stopped by a filter at <code>{activeRun.stoppedByStepId}</code>
                </p>
              )}
              {activeRun.steps.length === 0 ? (
                <p className="text-[12px] text-[color:var(--muted-foreground)]">
                  {activeRun.status === 'queued'
                    ? 'Queued — waiting for the executor.'
                    : 'No step data.'}
                </p>
              ) : (
                activeRun.steps.map((s) => <RunStepRow key={s.id} step={s} />)
              )}
            </>
          )}
        </div>
      </div>
    </section>
  );
}
