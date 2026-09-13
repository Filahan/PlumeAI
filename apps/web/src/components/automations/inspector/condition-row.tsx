'use client';

import { Trash2 } from 'lucide-react';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  UNARY_CONDITION_OPS,
  type Condition,
  type ConditionOp,
  type FieldValue,
} from '@/lib/automations/types';
import FieldValueInput from './schema-form/field-value-input';
import type { FieldMode } from './schema-form/mode-toggle';
import type { SchemaField } from './schema-form/schema';

/** Plain-language names for the comparison operators. */
export const OP_LABELS: Record<ConditionOp, string> = {
  eq: 'is',
  neq: 'is not',
  contains: 'contains',
  not_contains: 'does not contain',
  gt: '>',
  gte: '≥',
  lt: '<',
  lte: '≤',
  is_empty: 'is empty',
  is_not_empty: 'is not empty',
  is_true: 'is true',
  is_false: 'is false',
};

/** Filter rules compare two values; neither side may be an AI instruction. */
const SIDE_MODES: FieldMode[] = ['literal', 'ref'];

function side(name: string, label: string): SchemaField {
  return { name, label, description: '', required: true, schema: {}, kind: 'string' };
}

const LEFT = side('left', 'Value to check');
const RIGHT = side('right', 'Compare with');

function isUnary(op: ConditionOp): boolean {
  return (UNARY_CONDITION_OPS as readonly ConditionOp[]).includes(op);
}

/** One row of the rules builder: a value, a comparison, and (unless the comparison is
 *  unary) a second value. Ops that take no right operand must send `right: null` — the
 *  document schema rejects a leftover operand. */
export default function ConditionRow({
  stepId,
  condition,
  position,
  canRemove,
  onChange,
  onDraft,
  onFlush,
  onRemove,
}: {
  stepId: string;
  condition: Condition;
  /** Index in the rules list — part of the per-field debounce key. */
  position: number;
  canRemove: boolean;
  onChange(next: Condition): void;
  onDraft(next: Condition, key: string): void;
  onFlush(key: string): void;
  onRemove(): void;
}) {
  const unary = isUnary(condition.op);
  const keyFor = (name: string) => `rules.${position}.${name}`;

  const setSide = (
    name: 'left' | 'right',
    next: FieldValue | undefined,
    debounced: boolean
  ) => {
    const value = next ?? { kind: 'literal' as const, value: '' };
    const updated: Condition =
      name === 'left' ? { ...condition, left: value } : { ...condition, right: value };
    if (debounced) onDraft(updated, keyFor(name));
    else onChange(updated);
  };

  return (
    <div className="rounded-xl border border-[color:var(--border)] p-2.5 space-y-2">
      <div className="flex items-center gap-1.5">
        <span className="text-[11px] font-medium text-[color:var(--muted-foreground)]">
          Rule {position + 1}
        </span>
        <button
          type="button"
          onClick={onRemove}
          disabled={!canRemove}
          title={canRemove ? 'Remove this rule' : 'A filter needs at least one rule'}
          aria-label={`Remove rule ${position + 1}`}
          className="ml-auto text-[color:var(--muted-foreground)] hover:text-[#D4183D] disabled:opacity-30 disabled:pointer-events-none"
        >
          <Trash2 size={12} strokeWidth={2} />
        </button>
      </div>

      <FieldValueInput
        field={LEFT}
        value={condition.left}
        stepId={stepId}
        modes={SIDE_MODES}
        onChange={(next) => setSide('left', next, false)}
        onDraft={(next) => setSide('left', next, true)}
        onFlush={() => onFlush(keyFor('left'))}
      />

      <Select
        value={condition.op}
        onValueChange={(next) => {
          if (typeof next !== 'string') return;
          const op = next as ConditionOp;
          onChange({
            ...condition,
            op,
            right: isUnary(op) ? null : (condition.right ?? { kind: 'literal', value: '' }),
          });
        }}
      >
        <SelectTrigger
          aria-label="Comparison"
          className="w-full h-8 rounded-lg border-[color:var(--border)] bg-white text-[13px]"
        >
          <SelectValue>{OP_LABELS[condition.op]}</SelectValue>
        </SelectTrigger>
        <SelectContent className="rounded-xl">
          {(Object.keys(OP_LABELS) as ConditionOp[]).map((op) => (
            <SelectItem key={op} value={op} className="text-[13px]">
              {OP_LABELS[op]}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {!unary && (
        <FieldValueInput
          field={RIGHT}
          value={condition.right ?? undefined}
          stepId={stepId}
          modes={SIDE_MODES}
          onChange={(next) => setSide('right', next, false)}
          onDraft={(next) => setSide('right', next, true)}
          onFlush={() => onFlush(keyFor('right'))}
        />
      )}
    </div>
  );
}
