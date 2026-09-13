'use client';

import { useState } from 'react';
import { AlertTriangle, Pencil } from 'lucide-react';
import { useCatalog, useCurrentAutomation } from '@/lib/automations/store';
import { TextField } from '../text-field';
import ReferencePicker from './reference-picker';
import { previewValue, resolveRefSample } from './samples';
import type { JsonSchema } from './schema';
import { refMismatch } from './step-output-shape';

/** The "From step" side of a field: a `{{step_x.output.path}}` template.
 *
 *  Shown as a chip rather than an input, because the braces are noise to a
 *  non-technical reader — Edit reveals the raw text for anyone who wants it.
 *
 *  A reference that cannot fit the field — the whole output of an AI text step, which is
 *  the object `{"text": …}`, dropped into a string input — carries its warning here, next
 *  to the chip. The run would only say so after three retries. */
export default function RefField({
  stepId,
  label,
  value,
  fieldSchema,
  onChange,
  onDraft,
  onFlush,
}: {
  /** The step this field belongs to: only earlier steps can be referenced. */
  stepId: string;
  label: string;
  value: string;
  /** JSON schema of the field this reference fills, when the form knows one. */
  fieldSchema?: JsonSchema | null;
  onChange(next: string): void;
  onDraft(next: string): void;
  onFlush(): void;
}) {
  const current = useCurrentAutomation();
  const catalog = useCatalog();
  const [editing, setEditing] = useState(false);
  const sample = resolveRefSample(current?.activeRun, value);
  const mismatch = refMismatch(
    current?.document.steps ?? [],
    catalog,
    current?.activeRun,
    value,
    fieldSchema
  );

  if (!editing && value.trim().length === 0) {
    return (
      <div className="flex items-center gap-1.5">
        <ReferencePicker
          beforeStepId={stepId}
          fieldSchema={fieldSchema}
          label="Choose a step value"
          onPick={(ref) => onChange(ref)}
        />
        <button
          type="button"
          onClick={() => setEditing(true)}
          className="text-[11px] text-[color:var(--muted-foreground)] hover:text-[color:var(--foreground)] underline underline-offset-2"
        >
          or type it
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-1">
      {editing ? (
        <div className="flex items-center gap-1.5">
          <TextField
            value={value}
            aria-label={`${label} reference`}
            placeholder="{{step_ab12cd.output.id}}"
            className="font-mono text-[12px] md:text-[12px]"
            onChange={onDraft}
            onFlush={() => {
              onFlush();
              setEditing(false);
            }}
          />
          <ReferencePicker
            beforeStepId={stepId}
            fieldSchema={fieldSchema}
            label="Pick"
            onPick={(ref) => {
              onChange(ref);
              setEditing(false);
            }}
          />
        </div>
      ) : (
        <div className="flex items-center gap-1.5 min-w-0">
          <code className="min-w-0 flex-1 truncate h-7 inline-flex items-center px-2 rounded-lg bg-[color:var(--surface-muted)] text-[11px] font-mono">
            {value}
          </code>
          <button
            type="button"
            onClick={() => setEditing(true)}
            aria-label={`Edit the reference for ${label}`}
            className="shrink-0 inline-flex items-center gap-1 h-7 px-2 rounded-lg border border-[color:var(--border)] bg-white text-[11px] font-medium hover:bg-[color:var(--surface-muted)] transition"
          >
            <Pencil size={10} strokeWidth={2} />
            Edit
          </button>
          <ReferencePicker
            beforeStepId={stepId}
            fieldSchema={fieldSchema}
            label="Change"
            onPick={(ref) => onChange(ref)}
          />
        </div>
      )}

      {mismatch !== null && (
        <p className="flex items-start gap-1.5 rounded-lg bg-[#FFFBEB] px-2 py-1 text-[11px] leading-snug text-[#92400E]">
          <AlertTriangle size={12} strokeWidth={2} className="mt-[2px] shrink-0" />
          <span className="min-w-0 break-words">
            This value doesn&apos;t fit {label}: {mismatch}.
          </span>
        </p>
      )}

      {sample !== undefined && (
        <p className="text-[11px] text-[color:var(--muted-foreground)] truncate">
          Last run: <span className="font-mono">{previewValue(sample)}</span>
        </p>
      )}
    </div>
  );
}
