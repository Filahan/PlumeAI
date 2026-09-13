"use strict";
/** Turning a step's last run output into a pickable list of reference paths.
 *
 *  The backend has no schema for most action outputs (`outputSchema` is usually null),
 *  so the honest source of field names is what the step actually returned last time.
 *  Mirrors `app.services.refs`: object keys walk with `.key`, arrays with `[0]`.
 *  Pure functions — no React. */
Object.defineProperty(exports, "__esModule", { value: true });
exports.previewValue = previewValue;
exports.stepOutput = stepOutput;
exports.sampleFields = sampleFields;
exports.schemaFieldPaths = schemaFieldPaths;
exports.isCompleteRef = isCompleteRef;
exports.parseRef = parseRef;
exports.resolveSamplePath = resolveSamplePath;
exports.resolveRefSample = resolveRefSample;
const MAX_FIELDS = 40;
const MAX_DEPTH = 2;
/** A short, single-line rendering of a sample value. */
function previewValue(value) {
    if (value === null)
        return 'null';
    if (value === undefined)
        return '—';
    if (typeof value === 'string') {
        const flat = value.replace(/\s+/g, ' ').trim();
        return flat.length > 60 ? `${flat.slice(0, 60)}…` : flat;
    }
    if (typeof value === 'number' || typeof value === 'boolean')
        return String(value);
    if (Array.isArray(value))
        return `${value.length} item${value.length === 1 ? '' : 's'}`;
    if (typeof value === 'object') {
        const keys = Object.keys(value);
        return `{ ${keys.slice(0, 3).join(', ')}${keys.length > 3 ? ', …' : ''} }`;
    }
    return String(value);
}
/** The output the given step produced in `run`, or `undefined` when it didn't run. */
function stepOutput(run, stepId) {
    return run?.steps.find((s) => s.stepId === stepId)?.output;
}
function walk(value, prefix, depth, out) {
    if (out.length >= MAX_FIELDS)
        return;
    if (Array.isArray(value)) {
        if (value.length === 0)
            return;
        walk(value[0], `${prefix}[0]`, depth, out);
        return;
    }
    if (value === null || typeof value !== 'object')
        return;
    for (const [key, child] of Object.entries(value)) {
        if (out.length >= MAX_FIELDS)
            return;
        const path = `${prefix}.${key}`;
        out.push({ path, label: path.replace(/^\./, ''), preview: previewValue(child) });
        if (depth < MAX_DEPTH)
            walk(child, path, depth + 1, out);
    }
}
/** Every path worth offering under one step's output sample. */
function sampleFields(sample) {
    const out = [];
    walk(sample, '', 1, out);
    return out;
}
/** Paths derived from a declared JSON schema (an action's `outputSchema`, or an AI
 *  step's JSON output schema) rather than from a run. */
function schemaFieldPaths(schema) {
    const properties = schema && typeof schema.properties === 'object' && schema.properties !== null
        ? schema.properties
        : null;
    if (!properties)
        return [];
    return Object.keys(properties)
        .slice(0, MAX_FIELDS)
        .map((key) => {
        const child = properties[key];
        const type = typeof child?.type === 'string' ? child.type : '';
        return { path: `.${key}`, label: key, preview: type };
    });
}
const TOKEN_RE = /[A-Za-z0-9_]+|\[\d+\]/g;
/** Mirrors the backend's `REF_FULLMATCH_RE`: a `kind: "ref"` value must be exactly one
 *  `{{ path }}` and nothing else, or the document is rejected outright. */
const REF_FULLMATCH_RE = /^\{\{\s*[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+|\[\d+\])*\s*\}\}$/;
function isCompleteRef(text) {
    return REF_FULLMATCH_RE.test(text);
}
/** `{{step_x.output.items[0].id}}` → `{ stepId: 'step_x', path: '.output.items[0].id' }`. */
function parseRef(text) {
    const match = /^\s*\{\{\s*([^}]+?)\s*\}\}\s*$/.exec(text);
    if (!match)
        return null;
    const raw = match[1];
    const dot = raw.search(/[.[]/);
    return dot === -1
        ? { stepId: raw, path: '' }
        : { stepId: raw.slice(0, dot), path: raw.slice(dot) };
}
/** Resolve a path suffix (`.a[0].b`) against a sample value; `undefined` when it misses. */
function resolveSamplePath(sample, path) {
    let current = sample;
    for (const token of path.match(TOKEN_RE) ?? []) {
        if (current === null || current === undefined)
            return undefined;
        if (token.startsWith('[')) {
            const index = Number(token.slice(1, -1));
            if (!Array.isArray(current))
                return undefined;
            current = current[index];
        }
        else {
            if (typeof current !== 'object' || Array.isArray(current))
                return undefined;
            current = current[token];
        }
    }
    return current;
}
/** The sample value a whole `{{ ... }}` reference would resolve to in `run`, if any. */
function resolveRefSample(run, text) {
    const parsed = parseRef(text);
    if (!parsed || parsed.stepId === 'trigger')
        return undefined;
    const output = stepOutput(run, parsed.stepId);
    if (output === undefined)
        return undefined;
    return resolveSamplePath({ output }, parsed.path);
}
