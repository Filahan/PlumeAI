'use client';

import { useRef, useState } from 'react';
import type { AiOutput, AiStep } from '@/lib/automations/types';
import AiToolsPicker from './ai-tools-picker';
import JsonSchemaBuilder from './json-schema-builder';
import LabeledField from './labeled-field';
import RetrySettings from './retry-settings';
import ReferencePicker from './schema-form/reference-picker';
import { TextAreaField } from './text-field';
import { useStepPatch } from './use-step-patch';

const EMPTY_SCHEMA = { type: 'object', properties: {}, required: [] as string[] };

/** Settings for an `ai` step: what to do, which tools it may use, and what shape the
 *  answer should take.
 *
 *  `patch.settings` merges one level deep, so `output` is always sent whole — otherwise
 *  switching to JSON would drop the schema next to it. */
export default function AiStepForm({ step }: { step: AiStep }) {
  const { patchStep, patchStepDebounced, flushStep } = useStepPatch();
  const settings = step.settings;
  const instructionsRef = useRef<HTMLTextAreaElement | null>(null);
  const [emptyInstructions, setEmptyInstructions] = useState(false);

  const setInstructions = (text: string, debounced: boolean) => {
    // The schema demands a non-empty instruction: an emptied box stays local until the
    // user types something the API will accept — and says so, because "typed nothing,
    // nothing saved, no explanation" reads as a broken field.
    if (text.trim().length === 0) {
      setEmptyInstructions(true);
      return;
    }
    setEmptyInstructions(false);
    const patch = { settings: { instructions: text } };
    if (debounced) patchStepDebounced(step.id, 'instructions', patch);
    else patchStep(step.id, patch);
  };

  const setOutput = (output: AiOutput) => patchStep(step.id, { settings: { output } });

  /** Drop a `{{ ... }}` reference where the cursor was left. */
  const insertReference = (ref: string) => {
    const element = instructionsRef.current;
    const text = element?.value ?? settings.instructions;
    const caret = element?.selectionStart ?? text.length;
    setInstructions(`${text.slice(0, caret)}${ref}${text.slice(caret)}`, false);
  };

  return (
    <div className="space-y-3">
      <LabeledField
        label="What should the AI do?"
        hint="Write it as an instruction. Add values from earlier steps with the button below."
      >
        {(controlId) => (
          <TextAreaField
            id={controlId}
            rows={6}
            inputRef={instructionsRef}
            value={settings.instructions}
            placeholder="e.g. Summarise the emails above in three bullet points."
            onChange={(next) => setInstructions(next, true)}
            onFlush={() => flushStep(step.id, 'instructions')}
          />
        )}
      </LabeledField>
      {emptyInstructions && (
        <p className="text-[11px] text-[#D4183D]">
          Instructions can&apos;t be empty — the last saved version is still in use.
        </p>
      )}
      <ReferencePicker
        beforeStepId={step.id}
        label="Insert a value from an earlier step"
        onPick={insertReference}
      />

      <LabeledField
        label="Tools it may use"
        hint="The AI decides whether to call them. Leave everything off for a pure writing step."
      >
        <AiToolsPicker
          selected={settings.tools ?? []}
          onChange={(tools) => patchStep(step.id, { settings: { tools } })}
        />
      </LabeledField>

      <LabeledField label="What it gives back">
        <div className="inline-flex items-center gap-0.5 p-0.5 rounded-lg bg-[color:var(--surface-muted)]">
          {(['text', 'json'] as const).map((mode) => {
            const active = settings.output.mode === mode;
            return (
              <button
                key={mode}
                type="button"
                onClick={() =>
                  !active &&
                  setOutput(
                    mode === 'text'
                      ? { mode: 'text', schema: null }
                      : { mode: 'json', schema: settings.output.schema ?? EMPTY_SCHEMA }
                  )
                }
                aria-pressed={active}
                className={`px-2 py-[3px] rounded-md text-[10.5px] font-medium transition-colors ${
                  active
                    ? 'bg-white shadow-[0_1px_2px_rgba(0,0,0,0.06)]'
                    : 'text-[color:var(--muted-foreground)] hover:text-[color:var(--foreground)]'
                }`}
              >
                {mode === 'text' ? 'Plain text' : 'Structured fields'}
              </button>
            );
          })}
        </div>
      </LabeledField>

      {settings.output.mode === 'json' && (
        <LabeledField
          label="Fields to return"
          hint="Later steps can point at these by name."
        >
          <JsonSchemaBuilder
            schema={settings.output.schema ?? null}
            onChange={(schema) => setOutput({ mode: 'json', schema })}
          />
        </LabeledField>
      )}

      <RetrySettings step={step} />
    </div>
  );
}
