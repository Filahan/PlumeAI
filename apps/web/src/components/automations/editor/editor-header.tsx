'use client';

import { useState } from 'react';
import { Clock, History, Loader2, Play, Save, Sparkles, Square } from 'lucide-react';
import { Switch } from '@/components/ui/switch';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import NameEditor from '@/components/automations/editor/name-editor';
import {
  useAutomationsStore,
  useEditorIssues,
  useEditorRuns,
  type EditorMode,
} from '@/lib/automations/store';
import { capitalize, describeTrigger, isRunActive, triggerTimezone } from '@/lib/automations/types';
import { relativeFuture } from '@/lib/automations/format';
import { useIntervalRender } from '@/lib/automations/use-interval-render';

const MODES: { id: EditorMode; label: string }[] = [
  { id: 'design', label: 'Design' },
  { id: 'json', label: 'JSON' },
];

/** "next: in 12 min" is computed from `Date.now()`, so it needs a nudge to stay true. */
const NEXT_RUN_TICK_MS = 30_000;

/** The editor's top bar: identity + enable toggle on the left, mode switch and run
 *  actions on the right. Every control is bound straight to the store, one field at a
 *  time — a streaming run must not re-render this row on every text delta. */
export default function EditorHeader() {
  const setEnabled = useAutomationsStore((s) => s.setEnabled);
  const setMode = useAutomationsStore((s) => s.setMode);
  const confirmModeSwitch = useAutomationsStore((s) => s.confirmModeSwitch);
  const cancelModeSwitch = useAutomationsStore((s) => s.cancelModeSwitch);
  const toggleRunPanel = useAutomationsStore((s) => s.toggleRunPanel);
  const toggleAssistant = useAutomationsStore((s) => s.toggleAssistant);
  const startRun = useAutomationsStore((s) => s.startRun);
  const cancelRun = useAutomationsStore((s) => s.cancelRun);
  const saveDocument = useAutomationsStore((s) => s.saveDocument);

  const id = useAutomationsStore((s) => s.current?.id ?? '');
  const name = useAutomationsStore((s) => s.current?.name ?? '');
  const enabled = useAutomationsStore((s) => s.current?.enabled ?? false);
  const nextRunAt = useAutomationsStore((s) => s.current?.nextRunAt ?? null);
  const trigger = useAutomationsStore((s) => s.current?.document.trigger ?? null);
  const mode = useAutomationsStore((s) => s.current?.mode ?? 'design');
  const pendingModeSwitch = useAutomationsStore((s) => s.current?.pendingModeSwitch ?? null);
  const dirty = useAutomationsStore((s) => s.current?.dirty ?? false);
  const saving = useAutomationsStore((s) => s.current?.saving ?? false);
  const runPanelOpen = useAutomationsStore((s) => s.current?.runPanelOpen ?? false);
  const assistantOpen = useAutomationsStore((s) => s.current?.assistantOpen ?? false);
  const hasAssistantMessages = useAutomationsStore((s) => s.assistant.messages.length > 0);
  const runs = useEditorRuns();
  const issues = useEditorIssues();

  const [runBusy, setRunBusy] = useState(false);

  useIntervalRender(NEXT_RUN_TICK_MS, nextRunAt !== null);

  const running = runs.some((r) => isRunActive(r.status));
  const hasErrors = issues.some((i) => i.level === 'error');
  const timezone = triggerTimezone(trigger);

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
    <>
      <header className="shrink-0 flex items-center gap-3 px-4 h-14 border-b border-[color:var(--border)] bg-white">
        <NameEditor name={name} />

        <Tooltip>
          <TooltipTrigger
            render={(props) => (
              <span {...props} className="shrink-0 inline-flex">
                <Switch
                  checked={enabled}
                  onCheckedChange={(checked) => void setEnabled(id, checked)}
                  aria-label={enabled ? 'Disable automation' : 'Enable automation'}
                />
              </span>
            )}
          />
          <TooltipContent side="bottom">
            {enabled ? 'Enabled — the schedule is live' : 'Disabled'}
          </TooltipContent>
        </Tooltip>

        <span className="min-w-0 inline-flex items-center gap-1.5 h-7 px-2.5 rounded-full bg-[color:var(--surface-muted)] text-[11px] text-[color:var(--muted-foreground)]">
          <Clock size={11} strokeWidth={1.75} className="shrink-0" />
          <span className="truncate">
            {capitalize(describeTrigger(trigger))}
            {timezone && ` (${timezone})`}
          </span>
          {nextRunAt && (
            <span className="shrink-0 tabular-nums">· next: {relativeFuture(nextRunAt)}</span>
          )}
        </span>

        <div className="flex-1" />

        {/* Design | JSON */}
        <div className="flex items-center gap-0.5 p-0.5 rounded-lg bg-[color:var(--surface-muted)] shrink-0">
          {MODES.map((m) => {
            const active = m.id === mode;
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
        {mode === 'json' && (
          <button
            type="button"
            onClick={() => void saveDocument()}
            disabled={!dirty || saving}
            className="shrink-0 inline-flex items-center gap-1.5 h-8 px-3 rounded-xl border border-[color:var(--border)] text-[12px] font-medium hover:bg-[color:var(--surface-muted)] disabled:opacity-40 transition"
          >
            {saving ? (
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
          aria-pressed={runPanelOpen}
          className={`shrink-0 inline-flex items-center gap-1.5 h-8 px-3 rounded-xl text-[12px] font-medium transition ${
            runPanelOpen
              ? 'bg-[color:var(--surface-muted)]'
              : 'border border-[color:var(--border)] hover:bg-[color:var(--surface-muted)]'
          }`}
        >
          <History size={13} strokeWidth={2} />
          Runs
          {runs.length > 0 && (
            <span className="tabular-nums text-[10px] px-1.5 rounded-full bg-white border border-[color:var(--border)]">
              {runs.length}
            </span>
          )}
        </button>

        <button
          type="button"
          onClick={() => toggleAssistant()}
          aria-pressed={assistantOpen}
          className={`shrink-0 inline-flex items-center gap-1.5 h-8 px-3 rounded-xl text-[12px] font-medium transition ${
            assistantOpen
              ? 'bg-[color:var(--surface-muted)]'
              : 'border border-[color:var(--border)] hover:bg-[color:var(--surface-muted)]'
          }`}
        >
          <Sparkles size={13} strokeWidth={2} />
          Assistant
          {/* A conversation is waiting behind the button — say so without a number. */}
          {hasAssistantMessages && !assistantOpen && (
            <span className="w-1.5 h-1.5 rounded-full bg-[color:var(--primary)]" aria-hidden />
          )}
        </button>

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

      {/* Switching back to Design throws the JSON draft away, so ask in place — a
          browser `confirm()` would block the whole tab and looks nothing like the app. */}
      {pendingModeSwitch && (
        <div className="shrink-0 flex items-center gap-2 px-4 py-2 border-b border-[color:var(--border)] bg-[#f59e0b]/10">
          <p className="min-w-0 flex-1 text-[12px]">Discard unsaved JSON changes?</p>
          <button
            type="button"
            onClick={() => confirmModeSwitch()}
            className="shrink-0 h-7 px-2.5 rounded-lg bg-[#D4183D] text-white text-[11px] font-medium hover:opacity-90 transition"
          >
            Discard
          </button>
          <button
            type="button"
            onClick={() => cancelModeSwitch()}
            className="shrink-0 h-7 px-2.5 rounded-lg border border-[color:var(--border)] bg-white text-[11px] font-medium hover:bg-[color:var(--surface-muted)] transition"
          >
            Keep editing
          </button>
        </div>
      )}
    </>
  );
}
