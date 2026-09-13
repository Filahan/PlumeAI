'use client';

import { Workflow } from 'lucide-react';
import { useAutomationsStore, useCatalog, useCurrentAutomation } from '@/lib/automations/store';
import { capitalize, describeTrigger, stepLabel } from '@/lib/automations/types';
import { prettyJson } from '@/lib/automations/format';

/* ───────────────────────────────────────────────────────────────────────────────────
 * TEMPORARY — both components in this file are placeholders.
 *
 *   CanvasSlot    → replaced by the React Flow canvas in Task 2b.
 *   InspectorSlot → replaced by the step inspector in Task 2c.
 *
 * They exist so the editor is usable in the meantime, and so the shell already has the
 * two slots wired to the store: the canvas reads `document.steps` + `selection` and
 * calls `select(...)`; the inspector reads `selection` and edits through
 * `applyOperations(...)`. Neither keeps state of its own — do the same in 2b/2c.
 * ─────────────────────────────────────────────────────────────────────────────────── */

/** Placeholder canvas: the trigger plus one row per step, selectable. */
export function CanvasSlot() {
  const current = useCurrentAutomation();
  const catalog = useCatalog();
  const select = useAutomationsStore((s) => s.select);
  if (!current) return null;

  const { document: doc, selection } = current;
  const triggerSelected = selection?.kind === 'trigger';

  return (
    <div className="h-full overflow-y-auto px-8 py-6">
      <div className="mx-auto w-full max-w-[520px]">
        <div className="mb-3 flex items-center gap-1.5 text-[11px] uppercase tracking-[0.08em] text-[color:var(--muted-foreground)]">
          <Workflow size={12} strokeWidth={2} />
          Canvas (Task 2b)
        </div>

        <div className="space-y-2">
          <button
            type="button"
            onClick={() => select({ kind: 'trigger' })}
            className={`w-full text-left rounded-2xl border bg-white px-4 py-3 transition ${
              triggerSelected
                ? 'border-[color:var(--foreground)]/30 shadow-[0_1px_2px_rgba(0,0,0,0.06)]'
                : 'border-[color:var(--border)] hover:bg-[color:var(--surface-muted)]/50'
            }`}
          >
            <div className="text-[13px] font-medium">Trigger</div>
            <div className="text-[11px] text-[color:var(--muted-foreground)]">
              {capitalize(describeTrigger(doc.trigger))}
            </div>
          </button>

          {doc.steps.length === 0 ? (
            <p className="rounded-2xl border border-dashed border-[color:var(--border)] px-4 py-6 text-center text-[12px] text-[color:var(--muted-foreground)]">
              No steps yet. Step editing arrives with the canvas.
            </p>
          ) : (
            doc.steps.map((step, i) => {
              const isSelected =
                selection?.kind === 'step' && selection.stepId === step.id;
              return (
                <button
                  key={step.id}
                  type="button"
                  onClick={() => select({ kind: 'step', stepId: step.id })}
                  className={`w-full text-left rounded-2xl border bg-white px-4 py-3 transition ${
                    isSelected
                      ? 'border-[color:var(--foreground)]/30 shadow-[0_1px_2px_rgba(0,0,0,0.06)]'
                      : 'border-[color:var(--border)] hover:bg-[color:var(--surface-muted)]/50'
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <span className="w-5 h-5 shrink-0 rounded-md bg-[color:var(--surface-muted)] text-[10px] font-semibold inline-flex items-center justify-center tabular-nums">
                      {i + 1}
                    </span>
                    <span className="text-[13px] font-medium truncate">{step.name}</span>
                    <span className="ml-auto text-[10px] uppercase tracking-[0.06em] text-[color:var(--muted-foreground)]">
                      {step.type}
                    </span>
                    {!step.valid && (
                      <span className="text-[10px] text-[#D4183D] shrink-0">issues</span>
                    )}
                  </div>
                  <div className="mt-0.5 pl-7 text-[11px] text-[color:var(--muted-foreground)] truncate">
                    {stepLabel(step, catalog)}
                  </div>
                </button>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}

/** Placeholder inspector: raw JSON of whatever the canvas selected. */
export function InspectorSlot() {
  const current = useCurrentAutomation();
  if (!current) return null;

  const { document: doc, selection } = current;
  const selected =
    selection === null
      ? null
      : selection.kind === 'trigger'
        ? doc.trigger
        : (doc.steps.find((s) => s.id === selection.stepId) ?? null);

  return (
    <aside className="w-[320px] shrink-0 h-full border-l border-[color:var(--border)] bg-white flex flex-col">
      <div className="px-4 py-3 border-b border-[color:var(--border)]">
        <div className="text-[11px] uppercase tracking-[0.08em] text-[color:var(--muted-foreground)]">
          Inspector (Task 2c)
        </div>
        <div className="text-[13px] font-medium">
          {selection === null
            ? 'Nothing selected'
            : selection.kind === 'trigger'
              ? 'Trigger'
              : 'Step'}
        </div>
      </div>
      <div className="flex-1 overflow-auto p-3">
        {selected === null ? (
          <p className="text-[12px] text-[color:var(--muted-foreground)]">
            Select the trigger or a step to inspect it.
          </p>
        ) : (
          <pre className="text-[11px] font-mono whitespace-pre-wrap break-words rounded-lg bg-[color:var(--surface-muted)] p-3">
            {prettyJson(selected)}
          </pre>
        )}
      </div>
    </aside>
  );
}
