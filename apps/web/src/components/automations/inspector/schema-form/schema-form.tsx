'use client';

import { useEffect, useMemo, useRef } from 'react';
import { ChevronRight, X } from 'lucide-react';
import type { ActionStep, FieldValue } from '@/lib/automations/types';
import { useAutomationsStore } from '@/lib/automations/store';
import { useStepPatch } from '../use-step-patch';
import FieldValueInput from './field-value-input';
import { humanizeKey, literalKind, schemaFields, type JsonSchema, type SchemaField } from './schema';

/** Above this many fields the optional ones hide behind "More options". */
const COLLAPSE_ABOVE = 6;

/** A form for one action's `inputSchema`: required fields first, optional ones after.
 *
 *  Every edit rewrites the whole `input` map, because the backend merges `patch.settings`
 *  exactly one level deep — sending `{input: {query: …}}` would drop every other field. */
export default function SchemaForm({
  step,
  schema,
}: {
  step: ActionStep;
  schema: JsonSchema | null;
}) {
  const { patchStep, patchStepDebounced, flushStep } = useStepPatch();
  const input = useMemo(() => step.settings.input ?? {}, [step.settings.input]);
  const versionNumber = useAutomationsStore((s) => s.current?.versionNumber ?? 0);

  // The input map as this panel believes it to be, including edits whose round trip
  // hasn't come back yet — so a second edit builds on the first instead of erasing it.
  //
  // Reseeded only when the document actually moved forward (a *newer* version echoed
  // back) or when the panel switched steps. Adopting every `input` identity would let
  // an out-of-order echo — or a re-render carrying the pre-edit map — overwrite the
  // draft that is waiting on its debounce.
  const latest = useRef(input);
  const seen = useRef({ stepId: step.id, version: versionNumber });
  useEffect(() => {
    if (step.id !== seen.current.stepId || versionNumber > seen.current.version) {
      seen.current = { stepId: step.id, version: versionNumber };
      latest.current = input;
    }
  }, [input, step.id, versionNumber]);

  const commit = (name: string, next: FieldValue | undefined, debounced: boolean) => {
    const nextInput = { ...latest.current };
    if (next === undefined) delete nextInput[name];
    else nextInput[name] = next;
    latest.current = nextInput;
    const patch = { settings: { input: nextInput } };
    if (debounced) patchStepDebounced(step.id, `input.${name}`, patch);
    else patchStep(step.id, patch);
  };

  const fields = schemaFields(schema);
  const known = new Set(fields.map((f) => f.name));
  const extras = Object.keys(input).filter((name) => !known.has(name));
  const required = fields.filter((f) => f.required);
  const optional = fields.filter((f) => !f.required);
  const collapseOptional = fields.length > COLLAPSE_ABOVE && optional.length > 0;

  const row = (field: SchemaField) => (
    <FieldRow
      key={field.name}
      field={field}
      value={input[field.name]}
      stepId={step.id}
      onChange={(next) => commit(field.name, next, false)}
      onDraft={(next) => commit(field.name, next, true)}
      onFlush={() => flushStep(step.id, `input.${field.name}`)}
    />
  );

  if (fields.length === 0 && extras.length === 0) {
    return (
      <p className="text-[12px] text-[color:var(--muted-foreground)]">
        This action takes no settings.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      {required.map(row)}
      {!collapseOptional && optional.map(row)}

      {collapseOptional && (
        <details className="group">
          <summary className="flex items-center gap-1 cursor-pointer list-none text-[12px] font-medium text-[color:var(--muted-foreground)] hover:text-[color:var(--foreground)]">
            <ChevronRight
              size={12}
              strokeWidth={2}
              className="transition-transform group-open:rotate-90"
            />
            More options
            <span className="tabular-nums">({optional.length})</span>
          </summary>
          <div className="mt-3 space-y-3">{optional.map(row)}</div>
        </details>
      )}

      {extras.map((name) => (
        <FieldRow
          key={name}
          field={{
            name,
            label: humanizeKey(name),
            description: 'This action does not use this setting any more.',
            required: false,
            schema: {},
            kind: literalKind(name, {}),
          }}
          value={input[name]}
          stepId={step.id}
          onRemove={() => commit(name, undefined, false)}
          onChange={(next) => commit(name, next, false)}
          onDraft={(next) => commit(name, next, true)}
          onFlush={() => flushStep(step.id, `input.${name}`)}
        />
      ))}
    </div>
  );
}

function FieldRow({
  field,
  value,
  stepId,
  onChange,
  onDraft,
  onFlush,
  onRemove,
}: {
  field: SchemaField;
  value: FieldValue | undefined;
  stepId: string;
  onChange(next: FieldValue | undefined): void;
  onDraft(next: FieldValue | undefined): void;
  onFlush(): void;
  onRemove?(): void;
}) {
  return (
    <div className="space-y-1">
      <div className="flex items-baseline gap-1.5">
        {/* A `<span>`, not a `<label>`: the row below is a mode toggle plus whichever
            editor that mode needs, so there is no single control to point at. Each of
            those carries `aria-label={field.label}` instead. */}
        <span className="text-[12px] font-medium">
          {field.label}
          {field.required && (
            <span className="ml-0.5 text-[#D4183D]" title="Required">
              *
            </span>
          )}
        </span>
        {onRemove && (
          <button
            type="button"
            onClick={onRemove}
            aria-label={`Remove ${field.label}`}
            className="ml-auto inline-flex items-center gap-0.5 text-[11px] text-[color:var(--muted-foreground)] hover:text-[#D4183D]"
          >
            <X size={10} strokeWidth={2.25} /> Remove
          </button>
        )}
      </div>
      {field.description && (
        <p className="text-[11px] leading-snug text-[color:var(--muted-foreground)]">
          {field.description}
        </p>
      )}
      <FieldValueInput
        field={field}
        value={value}
        stepId={stepId}
        onChange={onChange}
        onDraft={onDraft}
        onFlush={onFlush}
      />
    </div>
  );
}
