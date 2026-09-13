'use client';

import AutomationCanvas from '@/components/automations/canvas/automation-canvas';
import { useCurrentAutomation } from '@/lib/automations/store';
import { prettyJson } from '@/lib/automations/format';

/* ───────────────────────────────────────────────────────────────────────────────────
 * CanvasSlot is final; InspectorSlot is a TEMPORARY placeholder until Task 2c lands.
 *
 *   CanvasSlot    → now the React Flow canvas (Task 2b).
 *   InspectorSlot → replaced by the step inspector in Task 2c.
 *
 * They exist so the editor is usable in the meantime, and so the shell already has the
 * two slots wired to the store: the canvas reads `document.steps` + `selection` and
 * calls `select(...)`; the inspector reads `selection` and edits through
 * `applyOperations(...)`. Neither keeps state of its own — do the same in 2b/2c.
 * ─────────────────────────────────────────────────────────────────────────────────── */

/** The automation canvas (Task 2b): React Flow rail, reads the store, renders the picker. */
export function CanvasSlot() {
  return (
    <div className="h-full min-h-0">
      <AutomationCanvas />
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
