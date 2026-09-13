/** One plain-English line for a filter step, for the canvas node and nothing else.
 *
 *  Pure — no React, no store. Deliberately terse: the node has ~40 characters before
 *  it truncates, and the full rule editor lives in the inspector.
 *
 *    { mode: 'rules', rules: { combinator: 'and', conditions: [
 *        { left: { kind: 'ref', value: '{{ step_a.output.count }}' }, op: 'gt',
 *          right: { kind: 'literal', value: 0 } } ] } }
 *      → "step_a.output.count > 0"
 *    { mode: 'ai', instruction: 'only keep urgent emails' }
 *      → "AI: only keep urgent emails"
 */

import type { Condition, ConditionOp, FieldValue, FilterSettings } from '@/lib/automations/types';
import { UNARY_CONDITION_OPS } from '@/lib/automations/types';

const OP_LABEL: Record<ConditionOp, string> = {
  eq: '=',
  neq: '≠',
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

export function truncate(text: string, max: number): string {
  const clean = text.replace(/\s+/g, ' ').trim();
  return clean.length > max ? `${clean.slice(0, max - 1)}…` : clean;
}

/** A field as a reader sees it: template braces stripped, literals as-is. */
function describeField(field: FieldValue | null | undefined): string {
  if (!field) return '?';
  if (field.kind === 'ref') {
    return truncate(String(field.value ?? '').replace(/^\{\{|\}\}$/g, ''), 28) || '?';
  }
  if (field.kind === 'ai') return `AI(${truncate(String(field.value ?? ''), 16)})`;
  const value = field.value;
  if (value === null || value === undefined || value === '') return 'empty';
  if (typeof value === 'object') return truncate(JSON.stringify(value), 20);
  return truncate(String(value), 20);
}

function describeCondition(condition: Condition): string {
  const op = OP_LABEL[condition.op] ?? condition.op;
  const left = describeField(condition.left);
  if ((UNARY_CONDITION_OPS as readonly string[]).includes(condition.op)) return `${left} ${op}`;
  return `${left} ${op} ${describeField(condition.right)}`;
}

export function describeFilter(settings: FilterSettings): string {
  if (settings.mode === 'ai') {
    const instruction = settings.instruction?.trim();
    return instruction ? `AI: ${truncate(instruction, 44)}` : 'AI condition — not written yet';
  }
  const conditions = settings.rules?.conditions ?? [];
  if (conditions.length === 0) return 'No conditions yet';
  const joiner = settings.rules?.combinator === 'or' ? ' or ' : ' and ';
  const rendered = conditions.map(describeCondition).join(joiner);
  return truncate(rendered, 56);
}
