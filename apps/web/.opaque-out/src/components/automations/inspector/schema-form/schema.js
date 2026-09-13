"use strict";
/** Reading a catalog action's `inputSchema` well enough to render a form for it.
 *
 *  Deliberately forgiving: the schemas come from the tool registry (OpenAI
 *  function-calling shape) and anything unrecognised degrades to a JSON textarea rather
 *  than breaking the panel. Pure functions — no React. */
Object.defineProperty(exports, "__esModule", { value: true });
exports.schemaType = schemaType;
exports.humanizeKey = humanizeKey;
exports.enumOptions = enumOptions;
exports.literalKind = literalKind;
exports.schemaFields = schemaFields;
exports.emptyLiteral = emptyLiteral;
exports.kindHint = kindHint;
/** Field names that almost always hold a paragraph rather than a word. */
const LONG_TEXT_NAME = /(body|content|text|message|markdown|html|prompt|instruction|comment|note|summary)/i;
const LONG_TEXT_FORMAT = new Set(['textarea', 'multiline', 'markdown', 'html']);
function asRecord(value) {
    return value !== null && typeof value === 'object' && !Array.isArray(value)
        ? value
        : null;
}
function asString(value) {
    return typeof value === 'string' ? value : '';
}
/** `type` may be a string or a union like `["string", "null"]`. */
function schemaType(schema) {
    const raw = schema.type;
    if (typeof raw === 'string')
        return raw;
    if (Array.isArray(raw)) {
        const first = raw.find((t) => typeof t === 'string' && t !== 'null');
        if (typeof first === 'string')
            return first;
    }
    return '';
}
/** `max_results` → `Max results`. */
function humanizeKey(name) {
    const spaced = name.replace(/[_-]+/g, ' ').replace(/([a-z\d])([A-Z])/g, '$1 $2').trim();
    return spaced.length === 0 ? name : spaced[0].toUpperCase() + spaced.slice(1);
}
/** Enum choices as strings, or `[]` when the field isn't an enum. */
function enumOptions(schema) {
    const raw = schema.enum;
    if (!Array.isArray(raw) || raw.length === 0)
        return [];
    return raw.filter((v) => typeof v === 'string' || typeof v === 'number').map((v) => String(v));
}
function literalKind(name, schema) {
    if (enumOptions(schema).length > 0)
        return 'enum';
    const type = schemaType(schema);
    if (type === 'boolean')
        return 'boolean';
    if (type === 'integer')
        return 'integer';
    if (type === 'number')
        return 'number';
    if (type === 'array') {
        const items = asRecord(schema.items);
        return items && schemaType(items) === 'string' ? 'string-array' : 'json';
    }
    if (type === 'string') {
        const description = asString(schema.description);
        const long = LONG_TEXT_NAME.test(name) ||
            LONG_TEXT_FORMAT.has(asString(schema.format).toLowerCase()) ||
            description.length > 120;
        return long ? 'text' : 'string';
    }
    return 'json';
}
/** The schema's fields, required ones first, each in a shape the form can render. */
function schemaFields(schema) {
    const properties = schema ? asRecord(schema.properties) : null;
    if (!properties)
        return [];
    const requiredList = Array.isArray(schema?.required)
        ? schema.required.filter((r) => typeof r === 'string')
        : [];
    const required = new Set(requiredList);
    const fields = Object.entries(properties).map(([name, raw]) => {
        const fieldSchema = asRecord(raw) ?? {};
        return {
            name,
            label: humanizeKey(name),
            description: asString(fieldSchema.description),
            required: required.has(name),
            schema: fieldSchema,
            kind: literalKind(name, fieldSchema),
        };
    });
    // Required first, then the declared order — never alphabetical, the tool authors put
    // the interesting fields first.
    return [...fields.filter((f) => f.required), ...fields.filter((f) => !f.required)];
}
/** A sensible empty literal for a field the user has just switched to "Value". */
function emptyLiteral(kind, schema) {
    switch (kind) {
        case 'boolean':
            return false;
        case 'number':
        case 'integer':
            return '';
        case 'string-array':
            return [];
        case 'enum':
            return enumOptions(schema)[0] ?? '';
        case 'json':
            return null;
        default:
            return '';
    }
}
/** Short type hint shown next to a field label, e.g. `number`, `list of text`. */
function kindHint(kind) {
    switch (kind) {
        case 'number':
        case 'integer':
            return 'number';
        case 'boolean':
            return 'yes / no';
        case 'string-array':
            return 'list';
        case 'json':
            return 'JSON';
        case 'enum':
            return 'choice';
        default:
            return 'text';
    }
}
