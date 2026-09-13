'use client';

import { useMemo, useState, type ReactNode } from 'react';
import { Braces, Clock, CornerDownRight } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { useCatalog, useCurrentAutomation } from '@/lib/automations/store';
import { stepLabel, type AutomationStep, type Catalog } from '@/lib/automations/types';
import { cn } from '@/lib/utils';
import { isCompleteRef, stepOutput } from './samples';
import type { JsonSchema } from './schema';
import {
  pickableRows,
  stepOutputShape,
  type PickableRow,
} from './step-output-shape';

const TRIGGER_FIELDS: PickableRow[] = [
  {
    path: 'now',
    label: 'now',
    preview: 'when the run started (ISO timestamp)',
    valueType: 'string',
    warning: null,
  },
  {
    path: 'date',
    label: 'date',
    preview: "the run's date (YYYY-MM-DD)",
    valueType: 'string',
    warning: null,
  },
  {
    path: 'timezone',
    label: 'timezone',
    preview: 'the schedule timezone',
    valueType: 'string',
    warning: null,
  },
];

/** Dialog that builds a `{{step_id.output.path}}` reference from an earlier step.
 *
 *  What each step can offer — and in which order — is `stepOutputShape`: the value people
 *  actually want first, the whole output object last. Rows that cannot fit the field being
 *  filled sink below the rest and say why, but stay pickable: the warning travels with the
 *  choice into the field (see `RefField`) rather than blocking it. */
export default function ReferencePicker({
  beforeStepId,
  fieldSchema,
  onPick,
  label,
  className,
}: {
  /** Only steps strictly before this one may be referenced; omit for "all steps". */
  beforeStepId?: string;
  /** JSON schema of the field being filled, when there is one — what makes an object in a
   *  string field visible before the run rather than after it. */
  fieldSchema?: JsonSchema | null;
  onPick(ref: string): void;
  label: string;
  className?: string;
}) {
  const current = useCurrentAutomation();
  const catalog = useCatalog();
  const [open, setOpen] = useState(false);
  const [custom, setCustom] = useState('');

  const steps = useMemo(() => {
    const all = current?.document.steps ?? [];
    const cut = beforeStepId ? all.findIndex((s) => s.id === beforeStepId) : -1;
    return cut === -1 ? all : all.slice(0, cut);
  }, [current?.document.steps, beforeStepId]);

  const choose = (ref: string) => {
    onPick(ref);
    setOpen(false);
    setCustom('');
  };

  // A `kind: "ref"` value must be exactly one `{{ path }}` or the document is rejected
  // outright, so check the path here rather than letting the API answer for us.
  const typed = custom.trim();
  const typedRef = `{{${typed}}}`;
  const typedValid = typed.length > 0 && isCompleteRef(typedRef);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={cn(
          'inline-flex items-center gap-1 h-7 px-2 rounded-lg border border-[color:var(--border)] bg-white text-[11px] font-medium hover:bg-[color:var(--surface-muted)] transition',
          className
        )}
      >
        <Braces size={11} strokeWidth={2} />
        {label}
      </button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-[420px] max-h-[70vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Use a value from an earlier step</DialogTitle>
            <DialogDescription>
              Pick the value you want. It is filled in each time the automation runs.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-3">
            <Source title="Trigger" icon={<Clock size={11} strokeWidth={2} />}>
              {TRIGGER_FIELDS.map((f) => (
                <FieldRow
                  key={f.path}
                  row={f}
                  onClick={() => choose(`{{trigger.${f.path}}}`)}
                />
              ))}
            </Source>

            {steps.length === 0 && (
              <p className="text-[12px] text-[color:var(--muted-foreground)]">
                No earlier steps yet — only the trigger is available here.
              </p>
            )}

            {steps.map((step, index) => (
              <StepSource
                key={step.id}
                step={step}
                index={index}
                catalog={catalog}
                sample={stepOutput(current?.activeRun, step.id)}
                fieldSchema={fieldSchema}
                onPick={choose}
              />
            ))}

            <div className="rounded-xl border border-[color:var(--border)] p-2.5">
              <div className="text-[11px] font-medium mb-1.5">Type a path yourself</div>
              <div className="flex items-center gap-1.5">
                <Input
                  value={custom}
                  onChange={(e) => setCustom(e.target.value)}
                  placeholder="step_ab12cd.output.items[0].id"
                  aria-label="Custom reference path"
                  className="h-8 rounded-lg border-[color:var(--border)] bg-white text-[12px] md:text-[12px] font-mono"
                />
                <button
                  type="button"
                  disabled={!typedValid}
                  onClick={() => choose(typedRef)}
                  className="shrink-0 h-8 px-3 rounded-lg bg-[color:var(--primary)] text-white text-[12px] font-medium disabled:opacity-40"
                >
                  Use
                </button>
              </div>
              {typed.length > 0 && !typedValid && (
                <p className="mt-1 text-[11px] text-[#D4183D]">
                  Use one path made of names, dots and <code>[0]</code> indexes — no braces,
                  spaces or extra text.
                </p>
              )}
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}

function Source({
  title,
  subtitle,
  icon,
  children,
}: {
  title: string;
  subtitle?: string;
  icon?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="rounded-xl border border-[color:var(--border)] overflow-hidden">
      <div className="flex items-center gap-1.5 px-2.5 py-1.5 bg-[color:var(--surface-muted)] text-[11px] font-medium">
        {icon}
        <span className="truncate">{title}</span>
        {subtitle && (
          <span className="ml-auto text-[10px] text-[color:var(--muted-foreground)] truncate">
            {subtitle}
          </span>
        )}
      </div>
      <div className="divide-y divide-[color:var(--border)]">{children}</div>
    </div>
  );
}

function StepSource({
  step,
  index,
  catalog,
  sample,
  fieldSchema,
  onPick,
}: {
  step: AutomationStep;
  index: number;
  catalog: Catalog | null;
  /** What this step returned in the last run, when it ran. */
  sample: unknown;
  fieldSchema?: JsonSchema | null;
  onPick(ref: string): void;
}) {
  const label = stepLabel(step, catalog);
  const shape = stepOutputShape(step, catalog, sample, label);
  const rows = pickableRows(shape, fieldSchema);

  return (
    <Source
      title={`${index + 1}. ${step.name}`}
      subtitle={shape.source === 'run' ? 'from the last run' : label}
    >
      {rows.map((row) => (
        <FieldRow
          key={row.path}
          row={row}
          onClick={() => onPick(`{{${step.id}.output${row.path}}}`)}
        />
      ))}
      {shape.source === 'none' && (
        <p className="px-2.5 py-2 text-[11px] text-[color:var(--muted-foreground)]">
          No sample yet. Run the automation once, or type the path below.
        </p>
      )}
    </Source>
  );
}

function FieldRow({ row, onClick }: { row: PickableRow; onClick(): void }) {
  const note = row.warning ?? row.hint;
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'w-full px-2.5 py-1.5 text-left hover:bg-[color:var(--surface-muted)]/70 transition',
        row.warning !== null && 'opacity-70'
      )}
    >
      <span className="flex items-center gap-1.5">
        <CornerDownRight
          size={11}
          strokeWidth={2}
          className="shrink-0 text-[color:var(--muted-foreground)]"
        />
        <span className="text-[12px] font-mono truncate">{row.label}</span>
        {row.preview && (
          <span className="ml-auto text-[11px] text-[color:var(--muted-foreground)] truncate max-w-[45%]">
            {row.preview}
          </span>
        )}
      </span>
      {note && (
        <span
          className={cn(
            'mt-0.5 block pl-[18px] text-[11px] leading-snug',
            row.warning !== null ? 'text-[#92400E]' : 'text-[color:var(--muted-foreground)]'
          )}
        >
          {note}
        </span>
      )}
    </button>
  );
}
