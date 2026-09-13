'use client';

import { useState } from 'react';
import { Clock, History, Loader2, Play, Save, Sparkles, Square } from 'lucide-react';
import { Switch } from '@/components/ui/switch';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import NameEditor from '@/components/automations/editor/name-editor';
import {
  useAutomationsStore,
  type CurrentAutomation,
  type EditorMode,
} from '@/lib/automations/store';
import { capitalize, describeTrigger, isRunActive, triggerTimezone } from '@/lib/automations/types';
import { relativeFuture } from '@/lib/automations/format';

const MODES: { id: EditorMode; label: string }[] = [
  { id: 'design', label: 'Design' },
  { id: 'json', label: 'JSON' },
];

/** The editor's top bar: identity + enable toggle on the left, mode switch and run
 *  actions on the right. Every control is bound straight to the store. */
export default function EditorHeader({ current }: { current: CurrentAutomation }) {
  const setEnabled = useAutomationsStore((s) => s.setEnabled);
  const setMode = useAutomationsStore((s) => s.setMode);
  const toggleRunPanel = useAutomationsStore((s) => s.toggleRunPanel);
  const startRun = useAutomationsStore((s) => s.startRun);
  const cancelRun = useAutomationsStore((s) => s.cancelRun);
  const saveDocument = useAutomationsStore((s) => s.saveDocument);
  const [runBusy, setRunBusy] = useState(false);

  const running = current.runs.some((r) => isRunActive(r.status));
  const hasErrors = current.issues.some((i) => i.level === 'error');
  const timezone = triggerTimezone(current.document.trigger);

  const onRunClick = async () => {
    if (runBusy) return;
    setRunBusy(true);
    try {
      if (running) await cancelRun();
      else await startRun('manual');
    } catch {
      // surfaced via current.saveError
    } finally {
      setRunBusy(false);
    }
  };

  return (
    <header className="shrink-0 flex items-center gap-3 px-4 h-14 border-b border-[color:var(--border)] bg-white">
      <NameEditor name={current.name} />

      <Tooltip>
        <TooltipTrigger
          render={(props) => (
            <span {...props} className="shrink-0 inline-flex">
              <Switch
                checked={current.enabled}
                onCheckedChange={(checked) => void setEnabled(current.id, checked)}
                aria-label={current.enabled ? 'Disable automation' : 'Enable automation'}
              />
            </span>
          )}
        />
        <TooltipContent side="bottom">
          {current.enabled ? 'Enabled — the schedule is live' : 'Disabled'}
        </TooltipContent>
      </Tooltip>

      <span className="min-w-0 inline-flex items-center gap-1.5 h-7 px-2.5 rounded-full bg-[color:var(--surface-muted)] text-[11px] text-[color:var(--muted-foreground)]">
        <Clock size={11} strokeWidth={1.75} className="shrink-0" />
        <span className="truncate">
          {capitalize(describeTrigger(current.document.trigger))}
          {timezone && ` (${timezone})`}
        </span>
        {current.nextRunAt && (
          <span className="shrink-0 tabular-nums">· next: {relativeFuture(current.nextRunAt)}</span>
        )}
      </span>

      <div className="flex-1" />

      {/* Design | JSON */}
      <div className="flex items-center gap-0.5 p-0.5 rounded-lg bg-[color:var(--surface-muted)] shrink-0">
        {MODES.map((m) => {
          const active = m.id === current.mode;
          return (
            <button
              key={m.id}
              type="button"
              onClick={() => setMode(m.id)}
              aria-pressed={active}
              className={`px-2.5 py-1 rounded-md text-[11px] font-medium transition-colors ${
                active
                  ? 'bg-white text-[color:var(--foreground)] shadow-[0_1px_2px_rgba(0,0,0,0.06)]'
                  : 'text-[color:var(--muted-foreground)] hover:text-[color:var(--foreground)]'
              }`}
            >
              {m.label}
            </button>
          );
        })}
      </div>

      {/* JSON mode saves explicitly; Design mode persists per operation. */}
      {current.mode === 'json' && (
        <button
          type="button"
          onClick={() => void saveDocument()}
          disabled={!current.dirty || current.saving}
          className="shrink-0 inline-flex items-center gap-1.5 h-8 px-3 rounded-xl border border-[color:var(--border)] text-[12px] font-medium hover:bg-[color:var(--surface-muted)] disabled:opacity-40 transition"
        >
          {current.saving ? (
            <Loader2 size={13} className="animate-spin" />
          ) : (
            <Save size={13} strokeWidth={2} />
          )}
          Save
        </button>
      )}

      <button
        type="button"
        onClick={() => toggleRunPanel()}
        aria-pressed={current.runPanelOpen}
        className={`shrink-0 inline-flex items-center gap-1.5 h-8 px-3 rounded-xl text-[12px] font-medium transition ${
          current.runPanelOpen
            ? 'bg-[color:var(--surface-muted)]'
            : 'border border-[color:var(--border)] hover:bg-[color:var(--surface-muted)]'
        }`}
      >
        <History size={13} strokeWidth={2} />
        Runs
        {current.runs.length > 0 && (
          <span className="tabular-nums text-[10px] px-1.5 rounded-full bg-white border border-[color:var(--border)]">
            {current.runs.length}
          </span>
        )}
      </button>

      <Tooltip>
        <TooltipTrigger
          render={(props) => (
            <span {...props} className="shrink-0 inline-flex">
              <button
                type="button"
                disabled
                className="inline-flex items-center gap-1.5 h-8 px-3 rounded-xl border border-[color:var(--border)] text-[12px] font-medium opacity-40 cursor-not-allowed"
              >
                <Sparkles size={13} strokeWidth={2} />
                Assistant
              </button>
            </span>
          )}
        />
        <TooltipContent side="bottom">Coming soon</TooltipContent>
      </Tooltip>

      <button
        type="button"
        onClick={() => void onRunClick()}
        disabled={runBusy || (!running && hasErrors)}
        title={!running && hasErrors ? 'Fix the errors below before running' : undefined}
        className={`shrink-0 inline-flex items-center gap-1.5 h-8 px-3.5 rounded-xl text-[12px] font-medium transition disabled:opacity-40 ${
          running
            ? 'border border-[color:var(--border)] hover:bg-[color:var(--surface-muted)]'
            : 'bg-[color:var(--primary)] text-white hover:opacity-90'
        }`}
      >
        {runBusy ? (
          <Loader2 size={13} className="animate-spin" />
        ) : running ? (
          <Square size={12} strokeWidth={2.25} />
        ) : (
          <Play size={13} strokeWidth={2} />
        )}
        {running ? 'Cancel' : 'Run now'}
      </button>
    </header>
  );
}
