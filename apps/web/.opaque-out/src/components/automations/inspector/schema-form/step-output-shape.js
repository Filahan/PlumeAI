"use strict";
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
Object.defineProperty(exports, "__esModule", { value: true });
exports.valueTypeOf = valueTypeOf;
exports.stepOutputShape = stepOutputShape;
exports.expectedScalar = expectedScalar;
exports.valueMismatch = valueMismatch;
exports.pickableRows = pickableRows;
exports.refValueType = refValueType;
exports.refMismatch = refMismatch;
const types_1 = require("@/lib/automations/types");
const samples_1 = require("./samples");
const schema_1 = require("./schema");
const WHOLE_LABEL = 'Whole result';
const WHOLE_LABEL_DEMOTED = 'Whole result (object)';
const AI_TEXT_HINT = 'an object with a text field — rarely what you want';
const GENERIC_WHOLE_HINT = 'every field at once — usually pick one of the values above';
/** The JSON type of a concrete sample value. */
function valueTypeOf(value) {
    if (value === null)
        return 'null';
    if (Array.isArray(value))
        return 'array';
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
function asValueType(type) {
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
function rowsFromSchema(schema) {
    return (0, samples_1.schemaFieldPaths)(schema).map((field) => ({
        ...field,
        valueType: asValueType(field.preview),
    }));
}
/** Rows read off the last run's output, typed by the sample value each one resolves to. */
function rowsFromSample(sample) {
    return (0, samples_1.sampleFields)(sample).map((field) => ({
        ...field,
        valueType: valueTypeOf((0, samples_1.resolveSamplePath)(sample, field.path)),
    }));
}
/** The `{{step_x.output}}` row. Typed `object` only when we know field names sit under it
 *  — an action nobody has run and nobody declares could return anything, and calling that
 *  an object would put a warning on the only row we have to offer. */
function wholeRow(preview, hint) {
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
function withWhole(rows, source, wholePreview, wholeHint) {
    if (rows.length === 0)
        return { rows: [wholeRow(wholePreview)], source: 'none' };
    return { rows: [...rows, wholeRow(wholePreview, wholeHint)], source };
}
/** The rows the reference picker should offer for one step, best first.
 *
 *  `wholePreview` is the step's own label — what the whole-result row shows on its right. */
function stepOutputShape(step, catalog, sample, wholePreview) {
    if (step.type === 'ai') {
        // `run_ai_step` returns `{"text": …}` in text mode and the coerced object in JSON mode,
        // so the shape is known exactly — no need to guess from a run.
        if (step.settings.output.mode === 'text') {
            return withWhole([{ path: '.text', label: 'Text', preview: "the AI step's answer", valueType: 'string' }], 'schema', wholePreview, AI_TEXT_HINT);
        }
        const declared = rowsFromSchema(step.settings.output.schema);
        if (declared.length > 0) {
            return withWhole(declared, 'schema', wholePreview, GENERIC_WHOLE_HINT);
        }
        return withWhole(rowsFromSample(sample), 'run', wholePreview, GENERIC_WHOLE_HINT);
    }
    if (step.type === 'filter') {
        // `run_filter_step` always returns `{"continue": bool, "reason": str}`.
        return withWhole([
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
        ], 'schema', wholePreview, GENERIC_WHOLE_HINT);
    }
    const action = (0, types_1.findCatalogAction)(catalog, step.settings.integration, step.settings.action);
    const declared = rowsFromSchema(action?.outputSchema ?? null);
    if (declared.length > 0)
        return withWhole(declared, 'schema', wholePreview, GENERIC_WHOLE_HINT);
    return withWhole(rowsFromSample(sample), 'run', wholePreview, GENERIC_WHOLE_HINT);
}
// ─── fitting a value into the field it is wired to ──────────────────────────────────
/** The single value a target field holds, or `null` when it takes structured data (or
 *  declares nothing, in which case we have no business complaining). */
function expectedScalar(schema) {
    if (!schema)
        return null;
    if ((0, schema_1.enumOptions)(schema).length > 0)
        return 'string';
    const type = (0, schema_1.schemaType)(schema);
    return type === 'string' || type === 'number' || type === 'integer' || type === 'boolean'
        ? type
        : null;
}
function expectedWord(expected) {
    if (expected === 'string')
        return 'text';
    if (expected === 'boolean')
        return 'yes / no';
    return 'a number';
}
/** Why `actual` can't go into a field expecting `expected`, or `null` when it fits.
 *
 *  Deliberately narrow: only a structured value landing in a single-value field. A string
 *  in a number field is the kind of thing the executor coerces, and warning about it would
 *  train people to ignore the warning that matters. */
function valueMismatch(expected, actual) {
    if (expected === null)
        return null;
    if (actual === 'object')
        return `this is an object, the field expects ${expectedWord(expected)}`;
    if (actual === 'array')
        return `this is a list, the field expects ${expectedWord(expected)}`;
    return null;
}
/** The step's rows ordered for one target field: everything that fits, in shape order,
 *  then everything that doesn't. Still pickable — the warning follows the choice into the
 *  field rather than blocking it. */
function pickableRows(shape, targetSchema) {
    const expected = expectedScalar(targetSchema);
    const rows = shape.rows.map((row) => ({ ...row, warning: valueMismatch(expected, row.valueType) }));
    // `sort` is stable, so each group keeps its best-first order.
    return rows.sort((a, b) => Number(a.warning !== null) - Number(b.warning !== null));
}
/** The type a written-out `{{step_x.output.path}}` resolves to, as far as we can tell. */
function refValueType(steps, catalog, run, ref) {
    const parsed = (0, samples_1.parseRef)(ref);
    if (!parsed)
        return '';
    // Every trigger field (`now` / `date` / `timezone`) is a string.
    if (parsed.stepId === 'trigger')
        return 'string';
    const step = steps.find((s) => s.id === parsed.stepId);
    if (!step)
        return '';
    // `{{step_x}}` on its own, or a path under something other than `output`: not ours.
    if (!/^\.output\b/.test(parsed.path))
        return '';
    const suffix = parsed.path.replace(/^\.output/, '');
    const sample = (0, samples_1.stepOutput)(run, step.id);
    const row = stepOutputShape(step, catalog, sample, '').rows.find((r) => r.path === suffix);
    if (row)
        return row.valueType;
    // A hand-typed path the shape doesn't know: the last run is the only witness.
    return sample === undefined ? '' : valueTypeOf((0, samples_1.resolveSamplePath)(sample, suffix));
}
/** Why the reference already in a field doesn't fit it, or `null` when it does. */
function refMismatch(steps, catalog, run, ref, targetSchema) {
    const expected = expectedScalar(targetSchema);
    if (expected === null)
        return null;
    return valueMismatch(expected, refValueType(steps, catalog, run, ref));
}
