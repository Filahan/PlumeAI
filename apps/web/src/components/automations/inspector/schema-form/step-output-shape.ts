/** What a step actually produces, and whether that fits the field it is wired into.
 *
 *  The reference picker used to offer "Whole result" (`{{step_x.output}}`) first for every
 *  step, which is a trap: an AI step with `output.mode: "text"` produces the *object*
 *  `{"text": "…"}`, so a string input wired to the whole result receives an object and the
 *  action rejects it at run time. Here we work out the rows a step can offer — best first,
 *  with the whole result demoted whenever there is something better — and mark the ones
 *  that cannot fit the target field.
 *
 *  Field names come from, in order: what the step is declared to produce (an AI step's
 *  output mode / schema, an action's catalog `outputSchema`), then what it returned in the
 *  last run, then nothing. Pure functions — no React. */

import {
  findCatalogAction,
  type AutomationStep,
  type Catalog,
  type RunDetail,
} from '@/lib/automations/types';
import {
  parseRef,
  resolveSamplePath,
  sampleFields,
  schemaFieldPaths,
  stepOutput,
  type SampleField,
} from './samples';
import { enumOptions, schemaType, type JsonSchema } from './schema';

/** The JSON type of the value a row yields; `''` when nothing declares it. */
export type ValueType =
  | 'string'
  | 'number'
  | 'integer'
  | 'boolean'
  | 'object'
  | 'array'
  | 'null'
  | '';

/** One pickable value under a step's output. */
export interface OutputRow extends SampleField {
  valueType: ValueType;
  /** Muted second line — why this row is here but probably not what you want. */
  hint?: string;
}

export interface StepOutputShape {
  /** Best first. The whole-result row is last unless it is all we have. */
  rows: OutputRow[];
  /** Where the names came from, so the picker can say how solid they are. */
  source: 'schema' | 'run' | 'none';
}

const WHOLE_LABEL = 'Whole result';
const WHOLE_LABEL_DEMOTED = 'Whole result (object)';
const AI_TEXT_HINT = 'an object with a text field — rarely what you want';
const GENERIC_WHOLE_HINT = 'every field at once — usually pick one of the values above';

/** The JSON type of a concrete sample value. */
export function valueTypeOf(value: unknown): ValueType {
  if (value === null) return 'null';
  if (Array.isArray(value)) return 'array';
  switch (typeof value) {
    case 'string':
      return 'string';
    case 'number':
      return 'number';
    case 'boolean':
      return 'boolean';
    case 'object':
      return 'object';
    default:
      return '';
  }
}

function asValueType(type: string): ValueType {
  switch (type) {
    case 'string':
    case 'number':
    case 'integer':
    case 'boolean':
    case 'object':
    case 'array':
    case 'null':
      return type;
    default:
      return '';
  }
}

/** `schemaFieldPaths` rows, typed — its `preview` is already the declared JSON type. */
function rowsFromSchema(schema: Record<string, unknown> | null | undefined): OutputRow[] {
  return schemaFieldPaths(schema).map((field) => ({
    ...field,
    valueType: asValueType(field.preview),
  }));
}

/** Rows read off the last run's output, typed by the sample value each one resolves to. */
function rowsFromSample(sample: unknown): OutputRow[] {
  return sampleFields(sample).map((field) => ({
    ...field,
    valueType: valueTypeOf(resolveSamplePath(sample, field.path)),
  }));
}

/** The `{{step_x.output}}` row. Typed `object` only when we know field names sit under it
 *  — an action nobody has run and nobody declares could return anything, and calling that
 *  an object would put a warning on the only row we have to offer. */
function wholeRow(preview: string, hint?: string): OutputRow {
  return {
    path: '',
    label: hint === undefined ? WHOLE_LABEL : WHOLE_LABEL_DEMOTED,
    preview,
    valueType: hint === undefined ? '' : 'object',
    hint,
  };
}

/** Field rows plus the whole-result row in the right place: last when the rows above are
 *  worth more, first (and unlabelled as an object) when there is nothing better. */
function withWhole(
  rows: OutputRow[],
  source: StepOutputShape['source'],
  wholePreview: string,
  wholeHint: string
): StepOutputShape {
  if (rows.length === 0) return { rows: [wholeRow(wholePreview)], source: 'none' };
  return { rows: [...rows, wholeRow(wholePreview, wholeHint)], source };
}

/** The rows the reference picker should offer for one step, best first.
 *
 *  `wholePreview` is the step's own label — what the whole-result row shows on its right. */
export function stepOutputShape(
  step: AutomationStep,
  catalog: Catalog | null,
  sample: unknown,
  wholePreview: string
): StepOutputShape {
  if (step.type === 'ai') {
    // `run_ai_step` returns `{"text": …}` in text mode and the coerced object in JSON mode,
    // so the shape is known exactly — no need to guess from a run.
    if (step.settings.output.mode === 'text') {
      return withWhole(
        [{ path: '.text', label: 'Text', preview: "the AI step's answer", valueType: 'string' }],
        'schema',
        wholePreview,
        AI_TEXT_HINT
      );
    }
    const declared = rowsFromSchema(step.settings.output.schema);
    if (declared.length > 0) {
      return withWhole(declared, 'schema', wholePreview, GENERIC_WHOLE_HINT);
    }
    return withWhole(rowsFromSample(sample), 'run', wholePreview, GENERIC_WHOLE_HINT);
  }

  if (step.type === 'filter') {
    // `run_filter_step` always returns `{"continue": bool, "reason": str}`.
    return withWhole(
      [
        {
          path: '.continue',
          label: 'continue',
          preview: 'whether the run went on',
          valueType: 'boolean',
        },
        {
          path: '.reason',
          label: 'reason',
          preview: 'why it continued or stopped',
          valueType: 'string',
        },
      ],
      'schema',
      wholePreview,
      GENERIC_WHOLE_HINT
    );
  }

  const action = findCatalogAction(catalog, step.settings.integration, step.settings.action);
  const declared = rowsFromSchema(action?.outputSchema ?? null);
  if (declared.length > 0) return withWhole(declared, 'schema', wholePreview, GENERIC_WHOLE_HINT);
  return withWhole(rowsFromSample(sample), 'run', wholePreview, GENERIC_WHOLE_HINT);
}

// ─── fitting a value into the field it is wired to ──────────────────────────────────

/** The single value a target field holds, or `null` when it takes structured data (or
 *  declares nothing, in which case we have no business complaining). */
export function expectedScalar(
  schema: JsonSchema | null | undefined
): 'string' | 'number' | 'integer' | 'boolean' | null {
  if (!schema) return null;
  if (enumOptions(schema).length > 0) return 'string';
  const type = schemaType(schema);
  return type === 'string' || type === 'number' || type === 'integer' || type === 'boolean'
    ? type
    : null;
}

function expectedWord(expected: 'string' | 'number' | 'integer' | 'boolean'): string {
  if (expected === 'string') return 'text';
  if (expected === 'boolean') return 'yes / no';
  return 'a number';
}

/** Why `actual` can't go into a field expecting `expected`, or `null` when it fits.
 *
 *  Deliberately narrow: only a structured value landing in a single-value field. A string
 *  in a number field is the kind of thing the executor coerces, and warning about it would
 *  train people to ignore the warning that matters. */
export function valueMismatch(
  expected: 'string' | 'number' | 'integer' | 'boolean' | null,
  actual: ValueType
): string | null {
  if (expected === null) return null;
  if (actual === 'object') return `this is an object, the field expects ${expectedWord(expected)}`;
  if (actual === 'array') return `this is a list, the field expects ${expectedWord(expected)}`;
  return null;
}

/** A row as the picker renders it: with the reason it doesn't fit, when it doesn't. */
export interface PickableRow extends OutputRow {
  warning: string | null;
}

/** The step's rows ordered for one target field: everything that fits, in shape order,
 *  then everything that doesn't. Still pickable — the warning follows the choice into the
 *  field rather than blocking it. */
export function pickableRows(
  shape: StepOutputShape,
  targetSchema: JsonSchema | null | undefined
): PickableRow[] {
  const expected = expectedScalar(targetSchema);
  const rows = shape.rows.map((row) => ({ ...row, warning: valueMismatch(expected, row.valueType) }));
  // `sort` is stable, so each group keeps its best-first order.
  return rows.sort((a, b) => Number(a.warning !== null) - Number(b.warning !== null));
}

/** The type a written-out `{{step_x.output.path}}` resolves to, as far as we can tell. */
export function refValueType(
  steps: AutomationStep[],
  catalog: Catalog | null,
  run: RunDetail | null | undefined,
  ref: string
): ValueType {
  const parsed = parseRef(ref);
  if (!parsed) return '';
  // Every trigger field (`now` / `date` / `timezone`) is a string.
  if (parsed.stepId === 'trigger') return 'string';
  const step = steps.find((s) => s.id === parsed.stepId);
  if (!step) return '';
  // `{{step_x}}` on its own, or a path under something other than `output`: not ours.
  if (!/^\.output\b/.test(parsed.path)) return '';
  const suffix = parsed.path.replace(/^\.output/, '');
  const sample = stepOutput(run, step.id);
  const row = stepOutputShape(step, catalog, sample, '').rows.find((r) => r.path === suffix);
  if (row) return row.valueType;
  // A hand-typed path the shape doesn't know: the last run is the only witness.
  return sample === undefined ? '' : valueTypeOf(resolveSamplePath(sample, suffix));
}

/** Why the reference already in a field doesn't fit it, or `null` when it does. */
export function refMismatch(
  steps: AutomationStep[],
  catalog: Catalog | null,
  run: RunDetail | null | undefined,
  ref: string,
  targetSchema: JsonSchema | null | undefined
): string | null {
  const expected = expectedScalar(targetSchema);
  if (expected === null) return null;
  return valueMismatch(expected, refValueType(steps, catalog, run, ref));
}
