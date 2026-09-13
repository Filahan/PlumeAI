/** Reading a catalog action's `inputSchema` well enough to render a form for it.
 *
 *  Deliberately forgiving: the schemas come from the tool registry (OpenAI
 *  function-calling shape) and anything unrecognised degrades to a JSON textarea rather
 *  than breaking the panel. Pure functions — no React. */

export type JsonSchema = Record<string, unknown>;

/** How the "Value" mode renders a field's literal editor. */
export type LiteralKind =
  | 'string'
  | 'text'
  | 'number'
  | 'integer'
  | 'boolean'
  | 'enum'
  | 'string-array'
  | 'json';

export interface SchemaField {
  name: string;
  label: string;
  description: string;
  required: boolean;
  schema: JsonSchema;
  kind: LiteralKind;
}

/** Field names that almost always hold a paragraph rather than a word. */
const LONG_TEXT_NAME = /(body|content|text|message|markdown|html|prompt|instruction|comment|note|summary)/i;
const LONG_TEXT_FORMAT = new Set(['textarea', 'multiline', 'markdown', 'html']);

function asRecord(value: unknown): JsonSchema | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as JsonSchema)
    : null;
}

function asString(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

/** `type` may be a string or a union like `["string", "null"]`. */
function schemaType(schema: JsonSchema): string {
  const raw = schema.type;
  if (typeof raw === 'string') return raw;
  if (Array.isArray(raw)) {
    const first = raw.find((t) => typeof t === 'string' && t !== 'null');
    if (typeof first === 'string') return first;
  }
  return '';
}

/** `max_results` → `Max results`. */
export function humanizeKey(name: string): string {
  const spaced = name.replace(/[_-]+/g, ' ').replace(/([a-z\d])([A-Z])/g, '$1 $2').trim();
  return spaced.length === 0 ? name : spaced[0].toUpperCase() + spaced.slice(1);
}

/** Enum choices as strings, or `[]` when the field isn't an enum. */
export function enumOptions(schema: JsonSchema): string[] {
  const raw = schema.enum;
  if (!Array.isArray(raw) || raw.length === 0) return [];
  return raw.filter((v) => typeof v === 'string' || typeof v === 'number').map((v) => String(v));
}

export function literalKind(name: string, schema: JsonSchema): LiteralKind {
  if (enumOptions(schema).length > 0) return 'enum';
  const type = schemaType(schema);
  if (type === 'boolean') return 'boolean';
  if (type === 'integer') return 'integer';
  if (type === 'number') return 'number';
  if (type === 'array') {
    const items = asRecord(schema.items);
    return items && schemaType(items) === 'string' ? 'string-array' : 'json';
  }
  if (type === 'string') {
    const description = asString(schema.description);
    const long =
      LONG_TEXT_NAME.test(name) ||
      LONG_TEXT_FORMAT.has(asString(schema.format).toLowerCase()) ||
      description.length > 120;
    return long ? 'text' : 'string';
  }
  return 'json';
}

/** The schema's fields, required ones first, each in a shape the form can render. */
export function schemaFields(schema: JsonSchema | null | undefined): SchemaField[] {
  const properties = schema ? asRecord(schema.properties) : null;
  if (!properties) return [];
  const requiredList = Array.isArray(schema?.required)
    ? schema.required.filter((r): r is string => typeof r === 'string')
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
export function emptyLiteral(kind: LiteralKind, schema: JsonSchema): unknown {
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
export function kindHint(kind: LiteralKind): string {
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
