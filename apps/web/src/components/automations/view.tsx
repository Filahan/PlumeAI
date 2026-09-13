'use client';

import { useEffect, useState } from 'react';
import {
  AutomationDetail,
  AutomationDocument,
  RunDetail,
  RunEvent,
  RunStep,
  RunSummary,
  ValidationIssue,
} from '@/lib/types';
import type { useAutomations } from '@/lib/hooks/use-automations';
import { ApiError } from '@/lib/api';
import ExecutionsOverview from '@/components/executions-overview';
import { AlertCircle, Clock, Loader2, Play, Square, Workflow } from 'lucide-react';

type AutomationsApi = ReturnType<typeof useAutomations>;

/** Shared dot color for both run statuses and run-step statuses — a superset of both
 *  enums, so one map covers the sidebar, the run list and the step cards. */
export const RUN_STATUS_DOT: Record<string, string> = {
  pending: 'bg-[color:var(--muted-foreground)]/40',
  queued: 'bg-[#f59e0b]',
  running: 'bg-[#6366f1]',
  succeeded: 'bg-[#10A37F]',
  failed: 'bg-[#D4183D]',
  skipped: 'bg-[color:var(--muted-foreground)]/40',
  cancelled: 'bg-[color:var(--muted-foreground)]/40',
};

const ACTIVE_RUN_STATUSES = new Set(['queued', 'running']);

function describeTrigger(trigger: AutomationDocument['trigger'] | undefined): string {
  if (!trigger) return 'Manual trigger';
  if (trigger.type === 'manual') return 'Manual trigger';
  const s = trigger.settings;
  if (s.mode === 'cron') return `Schedule: ${s.cron}${s.timezone ? ` (${s.timezone})` : ''}`;
  return `Every ${s.every_minutes} min${s.timezone ? ` (${s.timezone})` : ''}`;
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60_000).toFixed(1)}m`;
}

/* ─────────────────────────── Main view ─────────────────────────── */

export default function AutomationsView({
  selectedId, automations,
}: {
  selectedId: string | null;
  automations: AutomationsApi;
}) {
  return (
    <div className="w-full max-w-[760px] mx-auto px-8 py-8 overflow-y-auto h-full">
      <div className="mb-6">
        <h1 className="text-[20px] font-semibold tracking-tight flex items-center gap-2">
          <Workflow size={18} strokeWidth={1.75} /> Automations
        </h1>
        <p className="text-[11px] text-[color:var(--muted-foreground)]">
          Minimal JSON editor — the visual canvas builder lands in Phase 2.
        </p>
      </div>

      {automations.error && (
        <p className="mb-4 flex items-center gap-1.5 text-[12px] text-[#D4183D]">
          <AlertCircle size={14} strokeWidth={2} /> {automations.error}
        </p>
      )}

      {selectedId ? (
        <AutomationPanel key={selectedId} id={selectedId} api={automations} />
      ) : (
        <div className="rounded-2xl border border-[color:var(--border)] bg-white p-6 text-center text-[13px] text-[color:var(--muted-foreground)]">
          Select an automation on the left, or create a new one.
        </div>
      )}
    </div>
  );
}

/* ─────────────────────────── Detail panel ─────────────────────────── */

function AutomationPanel({ id, api }: { id: string; api: AutomationsApi }) {
  const [detail, setDetail] = useState<AutomationDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [jsonMode, setJsonMode] = useState<'view' | 'edit'>('view');
  const [jsonDraft, setJsonDraft] = useState('');
  const [issues, setIssues] = useState<ValidationIssue[]>([]);
  const [applyError, setApplyError] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);

  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  // Cache of fetched/streamed run details, keyed by run id — `selectedRun` is derived
  // from it below rather than stored separately, so no effect ever has to "clear" it.
  const [runDetails, setRunDetails] = useState<Record<string, RunDetail>>({});
  const [runBusy, setRunBusy] = useState(false);
  const [runActionError, setRunActionError] = useState<string | null>(null);

  const selectedRun = selectedRunId ? runDetails[selectedRunId] ?? null : null;
  const selectedRunStatus = selectedRun?.status;

  // Initial load. `id` is stable for this component's lifetime (the parent remounts it
  // via `key={selectedId}`), so this effectively only runs once per selected automation.
  useEffect(() => {
    let cancelled = false;
    Promise.all([api.getDetail(id), api.listRuns(id)])
      .then(([d, r]) => {
        if (cancelled) return;
        setDetail(d);
        setIssues(d.issues);
        setJsonDraft(JSON.stringify(d.document, null, 2));
        setRuns(r);
        setSelectedRunId(r[0]?.id ?? null);
      })
      .catch((e) => {
        if (!cancelled) setDetailError(e instanceof Error ? e.message : 'Failed to load automation');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [id, api]);

  // Fetch full detail for whichever run is selected.
  useEffect(() => {
    if (!selectedRunId) return;
    let cancelled = false;
    api
      .getRun(id, selectedRunId)
      .then((r) => {
        if (!cancelled) setRunDetails((prev) => ({ ...prev, [selectedRunId]: r }));
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [id, selectedRunId, api]);

  // Live-update the selected run while it's active (SSE, polling fallback inside the hook).
  useEffect(() => {
    if (!selectedRunId || !selectedRunStatus || !ACTIVE_RUN_STATUSES.has(selectedRunStatus)) return;
    const runId = selectedRunId;
    const unsubscribe = api.subscribeRun(id, runId, (evt: RunEvent) => {
      if (evt.type === 'snapshot') {
        setRunDetails((prev) => ({ ...prev, [runId]: evt.run }));
        return;
      }
      if (evt.type === 'run_finished') {
        setRunDetails((prev) => {
          const current = prev[runId];
          if (!current) return prev;
          return { ...prev, [runId]: { ...current, status: evt.status, error: evt.error ?? current.error } };
        });
        api.listRuns(id).then(setRuns).catch(() => {});
        return;
      }
      if (evt.type === 'step_started' || evt.type === 'step_finished' || evt.type === 'step_text') {
        setRunDetails((prev) => {
          const current = prev[runId];
          if (!current) return prev;
          const steps = current.steps.map((s): RunStep => {
            if (s.stepId !== evt.stepId) return s;
            if (evt.type === 'step_started') return { ...s, status: 'running', attempt: evt.attempt, index: evt.index };
            if (evt.type === 'step_finished') return { ...s, status: evt.status, output: evt.output ?? s.output };
            return { ...s, output: `${typeof s.output === 'string' ? s.output : ''}${evt.delta}` };
          });
          return { ...prev, [runId]: { ...current, steps } };
        });
      }
    });
    return unsubscribe;
  }, [id, selectedRunId, selectedRunStatus, api]);

  const toggleEnabled = async () => {
    if (!detail) return;
    const next = !detail.enabled;
    setDetail({ ...detail, enabled: next });
    try {
      await api.setEnabled(id, next);
    } catch {
      setDetail((d) => (d ? { ...d, enabled: !next } : d));
    }
  };

  const cancelEdit = () => {
    if (!detail) return;
    setJsonDraft(JSON.stringify(detail.document, null, 2));
    setApplyError(null);
    setJsonMode('view');
  };

  const applyJson = async () => {
    setApplying(true);
    setApplyError(null);
    try {
      const parsed = JSON.parse(jsonDraft) as AutomationDocument;
      const result = await api.putDocument(id, parsed);
      setIssues(result.issues);
      setJsonDraft(JSON.stringify(result.document, null, 2));
      setJsonMode('view');
      setDetail((d) => (d ? { ...d, document: result.document, versionNumber: result.versionNumber } : d));
    } catch (e) {
      if (e instanceof SyntaxError) {
        setApplyError(`Invalid JSON: ${e.message}`);
      } else if (e instanceof ApiError) {
        const extraIssues = (e.problem?.extra as { issues?: ValidationIssue[] } | undefined)?.issues;
        if (extraIssues) setIssues(extraIssues);
        setApplyError(e.message || 'The document was rejected.');
      } else {
        setApplyError(e instanceof Error ? e.message : 'Failed to apply changes');
      }
    } finally {
      setApplying(false);
    }
  };

  const runNow = async () => {
    setRunBusy(true);
    setRunActionError(null);
    try {
      const runId = await api.startRun(id);
      const rows = await api.listRuns(id);
      setRuns(rows);
      setSelectedRunId(runId);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setRunActionError('A run is already in progress.');
      } else {
        setRunActionError(e instanceof Error ? e.message : 'Failed to start run');
      }
    } finally {
      setRunBusy(false);
    }
  };

  const cancelSelectedRun = async () => {
    if (!selectedRunId) return;
    setRunBusy(true);
    setRunActionError(null);
    try {
      await api.cancelRun(id, selectedRunId);
      const r = await api.getRun(id, selectedRunId);
      setRunDetails((prev) => ({ ...prev, [selectedRunId]: r }));
      const rows = await api.listRuns(id);
      setRuns(rows);
    } catch (e) {
      setRunActionError(e instanceof Error ? e.message : 'Failed to cancel run');
    } finally {
      setRunBusy(false);
    }
  };

  if (loading && !detail) {
    return (
      <div className="flex items-center gap-1.5 text-[13px] text-[color:var(--muted-foreground)]">
        <Loader2 size={14} className="animate-spin" /> Loading…
      </div>
    );
  }
  if (detailError && !detail) {
    return (
      <div className="rounded-2xl border border-[color:var(--border)] bg-white p-4 flex items-center gap-1.5 text-[13px] text-[#D4183D]">
        <AlertCircle size={14} strokeWidth={2} /> {detailError}
      </div>
    );
  }
  if (!detail) return null;

  const anyActiveRun = runs.some((r) => ACTIVE_RUN_STATUSES.has(r.status));

  return (
    <div className="space-y-4">
      <div className="rounded-2xl border border-[color:var(--border)] bg-white p-4 space-y-3">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <NameEditor
            id={id}
            name={detail.name}
            api={api}
            onRenamed={(name) => setDetail((d) => (d ? { ...d, name } : d))}
          />
          <button
            type="button"
            onClick={() => void toggleEnabled()}
            className={`inline-flex items-center gap-1.5 h-7 px-2.5 rounded-full text-[11px] font-medium transition ${
              detail.enabled
                ? 'bg-[#10A37F]/10 text-[#10A37F]'
                : 'bg-[color:var(--surface-muted)] text-[color:var(--muted-foreground)]'
            }`}
          >
            <span
              className={`w-1.5 h-1.5 rounded-full ${detail.enabled ? 'bg-[#10A37F]' : 'bg-[color:var(--muted-foreground)]/50'}`}
            />
            {detail.enabled ? 'Enabled' : 'Disabled'}
          </button>
        </div>

        <div className="flex items-center gap-3 text-[12px] text-[color:var(--muted-foreground)] flex-wrap">
          <span className="inline-flex items-center gap-1">
            <Clock size={12} strokeWidth={1.75} /> {describeTrigger(detail.document?.trigger)}
          </span>
          {detail.nextRunAt && <span>Next run: {new Date(detail.nextRunAt).toLocaleString()}</span>}
          <span>v{detail.versionNumber}</span>
        </div>

        {issues.length > 0 && <IssuesList issues={issues} />}

        <div className="flex items-center gap-2 pt-1">
          {anyActiveRun ? (
            <button
              type="button"
              onClick={() => void cancelSelectedRun()}
              disabled={runBusy}
              className="inline-flex items-center gap-1.5 h-9 px-3 rounded-xl border border-[color:var(--border)] text-[13px] font-medium hover:bg-[color:var(--surface-muted)] transition disabled:opacity-40"
            >
              <Square size={13} strokeWidth={2} /> Cancel run
            </button>
          ) : (
            <button
              type="button"
              onClick={() => void runNow()}
              disabled={runBusy}
              className="inline-flex items-center gap-1.5 h-9 px-4 rounded-xl bg-[color:var(--primary)] text-white text-[13px] font-medium hover:opacity-90 transition disabled:opacity-40"
            >
              {runBusy ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} strokeWidth={2} />}
              Run now
            </button>
          )}
        </div>
        {runActionError && <p className="text-[12px] text-[#D4183D]">{runActionError}</p>}
      </div>

      <div className="rounded-2xl border border-[color:var(--border)] bg-white p-4 space-y-2">
        <div className="flex items-center justify-between">
          <h2 className="text-[13px] font-semibold">Document</h2>
          {jsonMode === 'view' ? (
            <button
              type="button"
              onClick={() => setJsonMode('edit')}
              className="h-7 px-2.5 rounded-full bg-[color:var(--surface-muted)] hover:bg-[color:var(--accent)] text-[12px] font-medium transition"
            >
              Edit JSON
            </button>
          ) : (
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={cancelEdit}
                disabled={applying}
                className="h-7 px-2.5 rounded-full border border-[color:var(--border)] text-[12px] font-medium hover:bg-[color:var(--surface-muted)] transition disabled:opacity-40"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => void applyJson()}
                disabled={applying}
                className="h-7 px-3 rounded-full bg-[color:var(--primary)] text-white text-[12px] font-medium hover:opacity-90 transition disabled:opacity-40 inline-flex items-center gap-1"
              >
                {applying && <Loader2 size={11} className="animate-spin" />} Apply
              </button>
            </div>
          )}
        </div>
        {jsonMode === 'view' ? (
          <pre className="text-[12px] font-mono bg-[color:var(--surface-muted)] rounded-lg p-3 overflow-x-auto max-h-[400px] overflow-y-auto whitespace-pre">
            {jsonDraft}
          </pre>
        ) : (
          <textarea
            value={jsonDraft}
            onChange={(e) => setJsonDraft(e.target.value)}
            spellCheck={false}
            rows={20}
            className="w-full font-mono text-[12px] bg-[color:var(--surface-muted)] rounded-lg p-3 outline-none resize-y"
          />
        )}
        {applyError && (
          <p className="flex items-center gap-1.5 text-[12px] text-[#D4183D]">
            <AlertCircle size={13} strokeWidth={2} /> {applyError}
          </p>
        )}
      </div>

      <div className="rounded-2xl border border-[color:var(--border)] bg-white p-4 space-y-3">
        <h2 className="text-[13px] font-semibold">Runs</h2>
        <ExecutionsOverview runs={runs} onSelectRun={setSelectedRunId} />
        <RunsPanel runs={runs} selectedRun={selectedRun} selectedRunId={selectedRunId} onSelectRun={setSelectedRunId} />
      </div>
    </div>
  );
}

/* ─────────────────────────── Name editor ─────────────────────────── */

function NameEditor({
  id, name, api, onRenamed,
}: {
  id: string;
  name: string;
  api: AutomationsApi;
  onRenamed: (name: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(name);

  const startEditing = () => {
    setDraft(name);
    setEditing(true);
  };

  const commit = async () => {
    setEditing(false);
    const trimmed = draft.trim();
    if (!trimmed || trimmed === name) {
      setDraft(name);
      return;
    }
    try {
      await api.rename(id, trimmed);
      onRenamed(trimmed);
    } catch {
      setDraft(name);
    }
  };

  if (editing) {
    return (
      <input
        autoFocus
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => void commit()}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            (e.target as HTMLInputElement).blur();
          } else if (e.key === 'Escape') {
            setDraft(name);
            setEditing(false);
          }
        }}
        className="text-[18px] font-semibold tracking-tight bg-transparent outline-none border-b border-[color:var(--border)] px-0.5"
      />
    );
  }

  return (
    <button
      type="button"
      onClick={startEditing}
      title="Click to rename"
      className="text-[18px] font-semibold tracking-tight text-left hover:bg-[color:var(--surface-muted)] rounded px-0.5 -mx-0.5 transition"
    >
      {name || 'Untitled automation'}
    </button>
  );
}

/* ─────────────────────────── Issues ─────────────────────────── */

function IssuesList({ issues }: { issues: ValidationIssue[] }) {
  return (
    <ul className="space-y-1">
      {issues.map((iss, i) => (
        <li
          key={`${iss.path}-${i}`}
          className={`text-[12px] flex items-start gap-1.5 ${
            iss.level === 'error' ? 'text-[#D4183D]' : 'text-[#b45309]'
          }`}
        >
          <AlertCircle size={12} strokeWidth={2} className="mt-0.5 shrink-0" />
          <span>
            <code className="text-[11px] opacity-70">{iss.path}</code> {iss.message}
          </span>
        </li>
      ))}
    </ul>
  );
}

/* ─────────────────────────── Runs panel ─────────────────────────── */

function RunsPanel({
  runs, selectedRun, selectedRunId, onSelectRun,
}: {
  runs: RunSummary[];
  selectedRun: RunDetail | null;
  selectedRunId: string | null;
  onSelectRun: (id: string) => void;
}) {
  return (
    <div className="grid grid-cols-[220px_1fr] gap-3">
      <div className="space-y-1 max-h-[360px] overflow-y-auto pr-1">
        {runs.length === 0 && (
          <p className="text-[12px] text-[color:var(--muted-foreground)] px-1">No runs yet</p>
        )}
        {runs.map((r) => (
          <button
            key={r.id}
            type="button"
            onClick={() => onSelectRun(r.id)}
            className={`w-full text-left rounded-lg px-2.5 py-2 text-[12px] transition ${
              r.id === selectedRunId ? 'bg-[color:var(--surface-muted)]' : 'hover:bg-[color:var(--surface-muted)]/60'
            }`}
          >
            <div className="flex items-center gap-1.5">
              <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${RUN_STATUS_DOT[r.status] ?? 'bg-gray-300'}`} />
              <span className="font-medium capitalize">{r.status}</span>
              <span className="ml-auto text-[10px] text-[color:var(--muted-foreground)] uppercase">{r.trigger}</span>
            </div>
            <div className="mt-0.5 text-[11px] text-[color:var(--muted-foreground)]">
              {r.startedAt ? new Date(r.startedAt).toLocaleString() : 'queued'}
              {r.durationMs != null && ` · ${formatDuration(r.durationMs)}`}
            </div>
          </button>
        ))}
      </div>
      <div className="min-w-0">
        {selectedRun ? (
          <RunStepsView run={selectedRun} />
        ) : (
          <p className="text-[12px] text-[color:var(--muted-foreground)]">Select a run to see details</p>
        )}
      </div>
    </div>
  );
}

function RunStepsView({ run }: { run: RunDetail }) {
  return (
    <div className="space-y-2">
      {run.error && (
        <p className="flex items-center gap-1.5 text-[12px] text-[#D4183D]">
          <AlertCircle size={13} strokeWidth={2} /> {run.error}
        </p>
      )}
      {run.steps.length === 0 ? (
        <p className="text-[12px] text-[color:var(--muted-foreground)]">
          {run.status === 'queued' ? 'Queued — waiting for the executor.' : 'No step data.'}
        </p>
      ) : (
        run.steps.map((s) => <RunStepCard key={s.id} step={s} />)
      )}
    </div>
  );
}

function RunStepCard({ step }: { step: RunStep }) {
  return (
    <details className="rounded-lg border border-[color:var(--border)] bg-[color:var(--surface-muted)] px-3 py-2">
      <summary className="flex items-center gap-2 cursor-pointer list-none text-[12px]">
        <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${RUN_STATUS_DOT[step.status] ?? 'bg-gray-300'}`} />
        <span className="font-medium truncate">{step.name}</span>
        <span className="text-[10px] uppercase text-[color:var(--muted-foreground)]">{step.type}</span>
        {step.attempt > 0 && (
          <span className="text-[10px] text-[color:var(--muted-foreground)]">attempt {step.attempt + 1}</span>
        )}
        <span className="ml-auto text-[11px] text-[color:var(--muted-foreground)] capitalize">{step.status}</span>
      </summary>
      <div className="mt-2 space-y-1.5">
        {step.error && <p className="text-[11px] text-[#D4183D]">{step.error}</p>}
        {step.output !== null && step.output !== undefined && (
          <pre className="text-[11px] whitespace-pre-wrap break-words text-[color:var(--muted-foreground)] max-h-48 overflow-y-auto">
            {typeof step.output === 'string' ? step.output : JSON.stringify(step.output, null, 2)}
          </pre>
        )}
      </div>
    </details>
  );
}
