'use client';

import { useEffect, useRef, useState } from 'react';
import { Plus } from 'lucide-react';
import type { Condition, FilterStep, Rules } from '@/lib/automations/types';
import ConditionRow from './condition-row';
import LabeledField from './labeled-field';
import { TextAreaField } from './text-field';
import { useStepPatch } from './use-step-patch';

/** Always true (`trigger.date` is filled on every run), exactly like the seed in
 *  `new-step.ts`: a rule the user has not filled in yet should not stop the run, and an
 *  empty literal against `is_not_empty` would do precisely that. */
const NEW_CONDITION: Condition = {
  left: { kind: 'ref', value: '{{trigger.date}}' },
  op: 'is_not_empty',
};
const DEFAULT_RULES: Rules = { combinator: 'and', conditions: [NEW_CONDITION] };
const DEFAULT_INSTRUCTION = 'Continue only if the result above is worth acting on.';

/** Client-side row ids — never persisted, only React keys. */
let rowSeq = 0;
function nextRowId(): string {
  rowSeq += 1;
  return `row${rowSeq}`;
}

/** Settings for a `filter` step: keep going, or stop the run here.
 *
 *  Two shapes, and the document schema is strict about both — rules mode needs at least
 *  one condition, AI mode needs a non-empty instruction — so the defaults above are what
 *  a mode switch sends rather than an empty shell the API would reject. */
export default function FilterForm({ step }: { step: FilterStep }) {
  const { patchStep, patchStepDebounced, flushStep } = useStepPatch();
  const settings = step.settings;
  const rules = settings.mode === 'rules' ? (settings.rules ?? DEFAULT_RULES) : DEFAULT_RULES;

  // Rules the panel believes in, including edits still in flight (see SchemaForm).
  const latest = useRef(rules);
  useEffect(() => {
    latest.current = rules;
  }, [rules]);

  // Row identity. Keying on the array index made React reuse a removed row's DOM — and
  // with it the local draft inside its inputs — for whatever slid up into its place.
  // The ids move with the rows instead: add and remove edit this list at the same
  // position they edit the conditions, so the row the user deleted is the row that
  // unmounts, one round trip before the document says so.
  //
  // The reconciliation below is the safety net for the document changing underneath us
  // (a JSON save, another operation's echo, a rejected write). It renders from the
  // fitted list rather than from state that is one render behind, which would key a row
  // by `undefined`.
  const [rowIds, setRowIds] = useState<string[]>(() => rules.conditions.map(() => nextRowId()));
  const conditionCount = rules.conditions.length;
  let ids = rowIds;
  if (rowIds.length !== conditionCount) {
    const fitted = rowIds.slice(0, conditionCount);
    while (fitted.length < conditionCount) fitted.push(nextRowId());
    setRowIds(fitted);
    ids = fitted;
  }

  const setRules = (next: Rules, debounceKey?: string) => {
    latest.current = next;
    const patch = { settings: { mode: 'rules', rules: next, instruction: null } };
    if (debounceKey) patchStepDebounced(step.id, debounceKey, patch);
    else patchStep(step.id, patch);
  };

  const setInstruction = (text: string, debounced: boolean) => {
    if (text.trim().length === 0) return;
    const patch = { settings: { mode: 'ai', instruction: text, rules: null } };
    if (debounced) patchStepDebounced(step.id, 'instruction', patch);
    else patchStep(step.id, patch);
  };

  const replaceCondition = (index: number, next: Condition, debounceKey?: string) => {
    const conditions = latest.current.conditions.map((c, i) => (i === index ? next : c));
    setRules({ ...latest.current, conditions }, debounceKey);
  };

  return (
    <div className="space-y-3">
      <div className="space-y-1.5">
        <ModeCard
          active={settings.mode === 'rules'}
          title="Check some rules"
          hint="Compare values and stop when they don't match"
          onClick={() => settings.mode !== 'rules' && setRules(rules)}
        />
        <ModeCard
          active={settings.mode === 'ai'}
          title="Ask the AI to decide"
          hint="Describe when the run should continue"
          onClick={() =>
            settings.mode !== 'ai' && setInstruction(settings.instruction || DEFAULT_INSTRUCTION, false)
          }
        />
      </div>

      {settings.mode === 'rules' ? (
        <div className="space-y-2">
          <LabeledField label="Continue when">
            <div className="inline-flex items-center gap-0.5 p-0.5 rounded-lg bg-[color:var(--surface-muted)]">
              {(['and', 'or'] as const).map((combinator) => {
                const active = rules.combinator === combinator;
                return (
                  <button
                    key={combinator}
                    type="button"
                    onClick={() => !active && setRules({ ...latest.current, combinator })}
                    aria-pressed={active}
                    className={`px-2 py-[3px] rounded-md text-[10.5px] font-medium transition-colors ${
                      active
                        ? 'bg-white shadow-[0_1px_2px_rgba(0,0,0,0.06)]'
                        : 'text-[color:var(--muted-foreground)] hover:text-[color:var(--foreground)]'
                    }`}
                  >
                    {combinator === 'and' ? 'all rules match' : 'any rule matches'}
                  </button>
                );
              })}
            </div>
          </LabeledField>

          {rules.conditions.map((condition, index) => (
            <ConditionRow
              key={ids[index]}
              stepId={step.id}
              position={index}
              condition={condition}
              canRemove={rules.conditions.length > 1}
              onChange={(next) => replaceCondition(index, next)}
              onDraft={(next, key) => replaceCondition(index, next, key)}
              onFlush={(key) => flushStep(step.id, key)}
              onRemove={() => {
                setRowIds((current) => current.filter((_, i) => i !== index));
                setRules({
                  ...latest.current,
                  conditions: latest.current.conditions.filter((_, i) => i !== index),
                });
              }}
            />
          ))}

          <button
            type="button"
            onClick={() => {
              setRowIds((current) => [...current, nextRowId()]);
              setRules({
                ...latest.current,
                conditions: [...latest.current.conditions, NEW_CONDITION],
              });
            }}
            className="inline-flex items-center gap-1 h-7 px-2.5 rounded-lg border border-[color:var(--border)] bg-white text-[11px] font-medium hover:bg-[color:var(--surface-muted)] transition"
          >
            <Plus size={11} strokeWidth={2.25} />
            Add a rule
          </button>
        </div>
      ) : (
        <LabeledField
          label="When should the run continue?"
          hint="Plain language. The AI answers yes or no each time the automation runs."
        >
          <TextAreaField
            rows={4}
            value={settings.instruction ?? ''}
            placeholder="e.g. Continue only if the email is from a customer asking for help."
            aria-label="When the run should continue"
            onChange={(next) => setInstruction(next, true)}
            onFlush={() => flushStep(step.id, 'instruction')}
          />
        </LabeledField>
      )}
    </div>
  );
}

function ModeCard({
  active,
  title,
  hint,
  onClick,
}: {
  active: boolean;
  title: string;
  hint: string;
  onClick(): void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`w-full px-3 py-2 rounded-xl border bg-white text-left transition ${
        active
          ? 'border-[color:var(--foreground)]/30 shadow-[0_1px_2px_rgba(0,0,0,0.06)]'
          : 'border-[color:var(--border)] hover:bg-[color:var(--surface-muted)]/60'
      }`}
    >
      <span className="block text-[12px] font-medium">{title}</span>
      <span className="block text-[11px] text-[color:var(--muted-foreground)]">{hint}</span>
    </button>
  );
}
