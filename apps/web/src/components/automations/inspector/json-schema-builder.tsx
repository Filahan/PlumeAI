'use client';

import { useState } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { prettyJson } from '@/lib/automations/format';
import { TextAreaField, TextField } from './text-field';

type FieldType = 'string' | 'number' | 'boolean' | 'array';

const TYPE_LABELS: Record<FieldType, string> = {
  string: 'Text',
  number: 'Number',
  boolean: 'Yes / no',
  array: 'List of text',
};

interface Row {
  name: string;
  type: FieldType;
  required: boolean;
}

function typeOf(raw: unknown): FieldType {
  const type = typeof raw === 'object' && raw !== null ? (raw as { type?: unknown }).type : '';
  if (type === 'number' || type === 'integer') return 'number';
  if (type === 'boolean') return 'boolean';
  if (type === 'array') return 'array';
  return 'string';
}

function toRows(schema: Record<string, unknown> | null): Row[] {
  const properties =
    schema && typeof schema.properties === 'object' && schema.properties !== null
      ? (schema.properties as Record<string, unknown>)
      : {};
  const required = Array.isArray(schema?.required) ? schema.required.map(String) : [];
  return Object.entries(properties).map(([name, raw]) => ({
    name,
    type: typeOf(raw),
    required: required.includes(name),
  }));
}

function toSchema(rows: Row[]): Record<string, unknown> {
  const properties: Record<string, unknown> = {};
  for (const row of rows) {
    if (row.name.trim().length === 0) continue;
    properties[row.name] =
      row.type === 'array' ? { type: 'array', items: { type: 'string' } } : { type: row.type };
  }
  return {
    type: 'object',
    properties,
    required: rows.filter((r) => r.required && r.name.trim().length > 0).map((r) => r.name),
  };
}

/** Describes the JSON an AI step should return: a row per field, or the raw schema for
 *  anyone who would rather write it out. Always emits `type: "object"` — the document
 *  validator insists on it. */
export default function JsonSchemaBuilder({
  schema,
  onChange,
}: {
  schema: Record<string, unknown> | null;
  onChange(next: Record<string, unknown>): void;
}) {
  const [raw, setRaw] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const rows = toRows(schema);

  const replace = (next: Row[]) => onChange(toSchema(next));

  if (raw) {
    return (
      <div className="space-y-1.5">
        <Toggle raw onClick={() => setRaw(false)} />
        <TextAreaField
          mono
          rows={8}
          value={prettyJson(schema ?? { type: 'object', properties: {} })}
          aria-label="Output schema"
          onChange={() => setError(null)}
          onFlush={(text) => {
            try {
              const parsed = JSON.parse(text) as unknown;
              if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
                setError('The schema must be a JSON object.');
                return;
              }
              setError(null);
              onChange(parsed as Record<string, unknown>);
            } catch (e) {
              setError(e instanceof Error ? e.message : 'Invalid JSON');
            }
          }}
        />
        {error && <p className="text-[11px] text-[#D4183D]">{error}</p>}
      </div>
    );
  }

  return (
    <div className="space-y-1.5">
      <Toggle raw={false} onClick={() => setRaw(true)} />

      {rows.length === 0 && (
        <p className="text-[11px] text-[color:var(--muted-foreground)]">
          No fields yet — add the pieces of information you want back.
        </p>
      )}

      {rows.map((row, index) => (
        <div key={`${row.name}-${index}`} className="flex items-center gap-1.5">
          <div className="min-w-0 flex-1">
            <TextField
              value={row.name}
              placeholder="field name"
              aria-label={`Field ${index + 1} name`}
              className="font-mono text-[12px] md:text-[12px]"
              onChange={() => {}}
              onFlush={(text) => {
                const name = text.trim();
                if (name.length === 0 || name === row.name) return;
                replace(rows.map((r, i) => (i === index ? { ...r, name } : r)));
              }}
            />
          </div>
          <div className="w-[92px] shrink-0">
            <Select
              value={row.type}
              onValueChange={(next) => {
                if (typeof next !== 'string') return;
                replace(rows.map((r, i) => (i === index ? { ...r, type: next as FieldType } : r)));
              }}
            >
              <SelectTrigger
                aria-label={`Field ${index + 1} type`}
                className="w-full h-8 rounded-lg border-[color:var(--border)] bg-white text-[12px]"
              >
                <SelectValue>{TYPE_LABELS[row.type]}</SelectValue>
              </SelectTrigger>
              <SelectContent className="rounded-xl">
                {(Object.keys(TYPE_LABELS) as FieldType[]).map((type) => (
                  <SelectItem key={type} value={type} className="text-[13px]">
                    {TYPE_LABELS[type]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <button
            type="button"
            onClick={() =>
              replace(rows.map((r, i) => (i === index ? { ...r, required: !r.required } : r)))
            }
            aria-pressed={row.required}
            title={row.required ? 'Required' : 'Optional'}
            className={`shrink-0 h-8 px-1.5 rounded-lg border text-[11px] font-medium transition ${
              row.required
                ? 'border-[color:var(--foreground)]/30 bg-[color:var(--surface-muted)]'
                : 'border-[color:var(--border)] text-[color:var(--muted-foreground)]'
            }`}
          >
            req
          </button>
          <button
            type="button"
            onClick={() => replace(rows.filter((_, i) => i !== index))}
            aria-label={`Remove field ${index + 1}`}
            className="shrink-0 text-[color:var(--muted-foreground)] hover:text-[#D4183D]"
          >
            <Trash2 size={12} strokeWidth={2} />
          </button>
        </div>
      ))}

      <button
        type="button"
        onClick={() =>
          replace([...rows, { name: `field_${rows.length + 1}`, type: 'string', required: false }])
        }
        className="inline-flex items-center gap-1 h-7 px-2.5 rounded-lg border border-[color:var(--border)] bg-white text-[11px] font-medium hover:bg-[color:var(--surface-muted)] transition"
      >
        <Plus size={11} strokeWidth={2.25} />
        Add a field
      </button>
    </div>
  );
}

function Toggle({ raw, onClick }: { raw: boolean; onClick(): void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="text-[11px] text-[color:var(--muted-foreground)] hover:text-[color:var(--foreground)] underline underline-offset-2"
    >
      {raw ? 'Back to the field list' : 'Edit raw schema'}
    </button>
  );
}
