'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { Clock, Filter, Sparkles, Trash2, X, Zap } from 'lucide-react';
import { Tabs, TabsList, TabsPanel, TabsTab } from '@/components/ui/tabs';
import IssuesList from '@/components/automations/issues-list';
import { useAutomationsStore, useEditorIssues } from '@/lib/automations/store';
import { capitalize, describeTrigger, type AutomationStep } from '@/lib/automations/types';
import ActionForm from './action-form';
import AiStepForm from './ai-step-form';
import FilterForm from './filter-form';
import StepNameEditor from './step-name-editor';
import StepOutput from './step-output';
import TriggerForm from './trigger-form';

const STEP_ICON = { action: Zap, ai: Sparkles, filter: Filter } as const;

/** Same confirm-in-place window the sidebar and the canvas shortcut use. */
const CONFIRM_MS = 2000;

/** Issues the server raised against one step, matched on its `steps[i]` path prefix. */
function issuePrefix(index: number): string {
  return `steps[${index}]`;
}

/** The editor's right-hand panel: everything about whatever the canvas has selected.
 *
 *  Props-less on purpose — it reads `selection` from the store, like the canvas does, so
 *  the two never disagree about what is being edited. */
export default function InspectorPanel() {
  // One field at a time: a streaming run rewrites `current.activeRun` constantly and
  // must not re-render the form the user is typing into.
  const doc = useAutomationsStore((s) => s.current?.document ?? null);
  const selection = useAutomationsStore((s) => s.current?.selection ?? null);
  const issues = useEditorIssues();
  const toggleInspector = useAutomationsStore((s) => s.toggleInspector);
  const applyOperations = useAutomationsStore((s) => s.applyOperations);
  const select = useAutomationsStore((s) => s.select);

  /** Delete arms first — one click shows "Delete?", a second within two seconds does it.
   *  Stored as the step it was armed *for*, so moving the selection disarms it without
   *  an effect having to notice. */
  const [armedStepId, setArmedStepId] = useState<string | null>(null);
  const timerRef = useRef<number | undefined>(undefined);

  useEffect(() => () => window.clearTimeout(timerRef.current), []);

  const selectedStepId = selection?.kind === 'step' ? selection.stepId : null;
  const armed = selectedStepId !== null && armedStepId === selectedStepId;

  const onDeleteClick = useCallback(() => {
    if (!selectedStepId) return;
    if (!armed) {
      setArmedStepId(selectedStepId);
      window.clearTimeout(timerRef.current);
      timerRef.current = window.setTimeout(() => setArmedStepId(null), CONFIRM_MS);
      return;
    }
    window.clearTimeout(timerRef.current);
    setArmedStepId(null);
    void applyOperations([{ op: 'remove_step', step_id: selectedStepId }])
      .then(() => select(null))
      .catch(() => {
        // `current.saveError` carries the reason; the shell shows it.
      });
  }, [applyOperations, armed, select, selectedStepId]);

  if (!doc) return null;

  const index = selection?.kind === 'step' ? doc.steps.findIndex((s) => s.id === selection.stepId) : -1;
  const step: AutomationStep | null = index >= 0 ? doc.steps[index] : null;
  const isTrigger = selection?.kind === 'trigger';
  const Icon = step ? STEP_ICON[step.type] : Clock;

  const stepIssues = step
    ? issues.filter((issue) => issue.path.startsWith(issuePrefix(index)))
    : [];

  return (
    <aside className="w-[320px] shrink-0 h-full border-l border-[color:var(--border)] bg-white flex flex-col">
      <div className="shrink-0 flex items-center gap-2 px-3 h-11 border-b border-[color:var(--border)]">
        {(isTrigger || step) && <Icon size={13} strokeWidth={1.75} className="shrink-0" />}
        {step ? (
          <StepNameEditor stepId={step.id} name={step.name} />
        ) : (
          <span className="min-w-0 flex-1 truncate text-[13px] font-medium">
            {isTrigger ? 'Trigger' : 'Nothing selected'}
          </span>
        )}
        {step && (
          <button
            type="button"
            onClick={onDeleteClick}
            aria-label={armed ? `Confirm deleting ${step.name}` : `Delete ${step.name}`}
            title="Delete this step"
            className={`shrink-0 inline-flex items-center gap-1 h-6 px-1.5 rounded-md text-[11px] font-medium transition ${
              armed
                ? 'bg-[#D4183D] text-white'
                : 'text-[color:var(--muted-foreground)] hover:bg-[color:var(--surface-muted)] hover:text-[#D4183D]'
            }`}
          >
            <Trash2 size={13} strokeWidth={2} />
            {armed && 'Delete?'}
          </button>
        )}
        <button
          type="button"
          onClick={() => toggleInspector()}
          aria-label="Close the panel"
          className="shrink-0 w-6 h-6 inline-flex items-center justify-center rounded-md text-[color:var(--muted-foreground)] hover:bg-[color:var(--surface-muted)] hover:text-[color:var(--foreground)] transition"
        >
          <X size={13} strokeWidth={2} />
        </button>
      </div>

      {selection === null || (selection.kind === 'step' && step === null) ? (
        <div className="flex-1 overflow-y-auto p-3">
          <p className="text-[12px] text-[color:var(--muted-foreground)]">
            Select the trigger or a step to edit it.
          </p>
        </div>
      ) : isTrigger ? (
        <div className="flex-1 overflow-y-auto p-3 space-y-3">
          <p className="text-[11px] text-[color:var(--muted-foreground)]">
            {capitalize(describeTrigger(doc.trigger))}.
          </p>
          <TriggerForm />
        </div>
      ) : (
        step && (
          <Tabs defaultValue="settings" className="flex-1 min-h-0">
            <div className="shrink-0 px-3 py-2 border-b border-[color:var(--border)]">
              <TabsList>
                <TabsTab value="settings">Settings</TabsTab>
                <TabsTab value="output">Output</TabsTab>
              </TabsList>
            </div>

            <TabsPanel value="settings" className="flex-1 min-h-0 overflow-y-auto p-3 space-y-3">
              {stepIssues.length > 0 && <IssuesList issues={stepIssues} />}
              {/* Keyed by step so moving the selection gives the form fresh local state
                  — pending debounces, draft text and row ids all belong to one step. */}
              {step.type === 'action' && <ActionForm key={step.id} step={step} />}
              {step.type === 'ai' && <AiStepForm key={step.id} step={step} />}
              {step.type === 'filter' && <FilterForm key={step.id} step={step} />}
            </TabsPanel>

            <TabsPanel value="output" className="flex-1 min-h-0 overflow-y-auto p-3">
              <StepOutput stepId={step.id} />
            </TabsPanel>
          </Tabs>
        )
      )}
    </aside>
  );
}
