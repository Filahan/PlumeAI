'use client';

import { useState } from 'react';
import type { FieldValue } from '@/lib/automations/types';
import { TextAreaField } from '../text-field';
import FieldModeToggle, { MODE_META, type FieldMode } from './mode-toggle';
import LiteralInput from './literal-input';
import RefField from './ref-field';
import { isCompleteRef } from './samples';
import { emptyLiteral, type SchemaField } from './schema';

export interface FieldValueInputProps {
  field: SchemaField;
  /** Missing means the field is absent from the step's input. */
  value: FieldValue | undefined;
  /** The step this field belongs to — bounds which steps can be referenced. */
  stepId: string;
  /** Restrict the modes on offer (filter conditions drop "Ask AI"). */
  modes?: FieldMode[];
  /** Commit now. `undefined` removes the field from the step's input. */
  onChange(next: FieldValue | undefined): void;
  /** Commit after the shared keystroke debounce. */
  onDraft(next: FieldValue | undefined): void;
  /** Flush a pending debounced commit. */
  onFlush(): void;
}

function asString(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

/** One step input, in whichever of the three modes it is currently using.
 *
 *  Value / From step / Ask AI map straight onto `FieldValue.kind`
 *  (`literal` / `ref` / `ai`). The document schema refuses a `ref` that isn't a complete
 *  `{{ path }}` and an `ai` instruction that is empty, so a mode the user has only just
 *  picked lives in local state until it holds something the server will accept — that
 *  way choosing "From step" never bounces off the API. */
export default function FieldValueInput({
  field,
  value,
  stepId,
  modes,
  onChange,
  onDraft,
  onFlush,
}: FieldValueInputProps) {
  const [pending, setPending] = useState<{ mode: FieldMode; text: string } | null>(null);
  // A pending mode stops mattering the moment the document comes back holding it — no
  // need to clear the state, just stop reading it.
  const active = pending !== null && value?.kind !== pending.mode ? pending : null;
  const mode: FieldMode = active?.mode ?? value?.kind ?? 'literal';

  const switchMode = (next: FieldMode) => {
    if (next === mode) return;
    // Text carries over between the modes that hold text, so switching after a typo
    // doesn't throw the sentence away.
    const carried = asString(value?.value);
    if (next === 'literal') {
      const keepsText = field.kind === 'string' || field.kind === 'text';
      setPending(null);
      onChange({
        kind: 'literal',
        value: keepsText && carried ? carried : emptyLiteral(field.kind, field.schema),
      });
      return;
    }
    const acceptable = next === 'ref' ? isCompleteRef(carried) : carried.trim().length > 0;
    if (acceptable) {
      setPending(null);
      onChange({ kind: next, value: carried });
    } else {
      setPending({ mode: next, text: next === 'ref' ? carried : '' });
    }
  };

  /** Commit `next` for a text-holding mode, keeping an uncommittable draft local. */
  const setText = (next: string, valid: boolean, debounced: boolean) => {
    if (active !== null) setPending({ mode, text: next });
    if (!valid) return;
    const fieldValue: FieldValue = { kind: mode, value: next };
    if (debounced) onDraft(fieldValue);
    else onChange(fieldValue);
  };

  const text = active !== null ? active.text : asString(value?.value);

  return (
    <div className="space-y-1.5">
      <FieldModeToggle mode={mode} modes={modes} onChange={switchMode} label={field.label} />

      {mode === 'literal' && (
        <LiteralInput
          field={field}
          value={value?.value}
          onChange={(next) =>
            onChange(next === undefined ? undefined : { kind: 'literal', value: next })
          }
          onDraft={(next) =>
            onDraft(next === undefined ? undefined : { kind: 'literal', value: next })
          }
          onFlush={onFlush}
        />
      )}

      {mode === 'ref' && (
        <RefField
          stepId={stepId}
          label={field.label}
          value={text}
          fieldSchema={field.schema}
          onChange={(next) => setText(next, isCompleteRef(next), false)}
          onDraft={(next) => setText(next, isCompleteRef(next), true)}
          onFlush={onFlush}
        />
      )}

      {mode === 'ai' && (
        <div className="space-y-1">
          <TextAreaField
            rows={2}
            value={text}
            placeholder="Describe what should go here, e.g. the summary from the previous step"
            aria-label={`What the AI should put in ${field.label}`}
            onChange={(next) => setText(next, next.trim().length > 0, true)}
            onFlush={() => onFlush()}
          />
          <p className="text-[11px] text-[color:var(--muted-foreground)]">{MODE_META.ai.hint}.</p>
        </div>
      )}
    </div>
  );
}
