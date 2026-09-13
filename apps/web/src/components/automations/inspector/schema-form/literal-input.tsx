'use client';

import { useState } from 'react';
import { X } from 'lucide-react';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { FIELD_CLASS, TextAreaField, TextField } from '../text-field';
import { enumOptions, type SchemaField } from './schema';

export interface LiteralInputProps {
  field: SchemaField;
  value: unknown;
  /** Commit now. `undefined` removes the field from the step's input entirely, which is
   *  what an emptied box means — a required field then reads as "missing", not "wrong". */
  onChange(next: unknown): void;
  /** Commit after the shared 500 ms keystroke debounce. */
  onDraft(next: unknown): void;
  /** Flush a pending debounced commit (blur / Enter). */
  onFlush(): void;
}

function asText(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  try {
    return JSON.stringify(value, null, 2) ?? '';
  } catch {
    return '';
  }
}

/** The "Value" side of a field: one editor per JSON-schema shape. */
export default function LiteralInput(props: LiteralInputProps) {
  const { field } = props;
  switch (field.kind) {
    case 'boolean':
      return <BooleanInput {...props} />;
    case 'enum':
      return <EnumInput {...props} />;
    case 'number':
    case 'integer':
      return <NumberInput {...props} />;
    case 'string-array':
      return <ChipsInput {...props} />;
    case 'json':
      return <JsonInput {...props} />;
    case 'text':
      return (
        <TextAreaField
          value={asText(props.value)}
          rows={4}
          placeholder={field.description || 'Type the text to use'}
          aria-label={field.label}
          onChange={(next) => props.onDraft(next)}
          onFlush={() => props.onFlush()}
        />
      );
    default:
      return (
        <TextField
          value={asText(props.value)}
          placeholder="Type a value"
          aria-label={field.label}
          onChange={(next) => props.onDraft(next)}
          onFlush={() => props.onFlush()}
        />
      );
  }
}

function BooleanInput({ field, value, onChange }: LiteralInputProps) {
  return (
    <label className="flex items-center gap-2 text-[12px] text-[color:var(--muted-foreground)]">
      <Switch
        checked={value === true}
        onCheckedChange={(checked) => onChange(checked)}
        aria-label={field.label}
      />
      {value === true ? 'Yes' : 'No'}
    </label>
  );
}

function EnumInput({ field, value, onChange }: LiteralInputProps) {
  const raw = Array.isArray(field.schema.enum) ? field.schema.enum : [];
  const options = enumOptions(field.schema);
  const selected = value === undefined || value === null ? '' : String(value);

  return (
    <Select
      value={selected}
      onValueChange={(next) => {
        if (typeof next !== 'string') return;
        const match = raw.find((r) => String(r) === next);
        onChange(match === undefined ? next : match);
      }}
    >
      <SelectTrigger
        aria-label={field.label}
        className="w-full h-8 rounded-lg border-[color:var(--border)] bg-white text-[13px]"
      >
        <SelectValue>{selected || 'Choose…'}</SelectValue>
      </SelectTrigger>
      <SelectContent className="rounded-xl">
        {options.map((option) => (
          <SelectItem key={option} value={option} className="text-[13px]">
            {option}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function NumberInput({ field, value, onDraft, onFlush }: LiteralInputProps) {
  return (
    <TextField
      type="number"
      value={asText(value)}
      placeholder="0"
      aria-label={field.label}
      onChange={(next) => {
        const trimmed = next.trim();
        if (trimmed === '') {
          onDraft(undefined);
          return;
        }
        const parsed = Number(trimmed);
        // Half-typed numbers ("-", "1e") are kept in the box but never committed: the
        // server would only answer with a type error the user is about to fix anyway.
        if (Number.isFinite(parsed)) onDraft(parsed);
      }}
      onFlush={() => onFlush()}
    />
  );
}

function ChipsInput({ field, value, onChange }: LiteralInputProps) {
  const items = Array.isArray(value) ? value.map((v) => String(v)) : [];
  const [entry, setEntry] = useState('');

  const add = () => {
    const next = entry
      .split(',')
      .map((v) => v.trim())
      .filter((v) => v.length > 0 && !items.includes(v));
    setEntry('');
    if (next.length > 0) onChange([...items, ...next]);
  };

  return (
    <div className="space-y-1.5">
      {items.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {items.map((item, i) => (
            <span
              key={`${item}-${i}`}
              className="inline-flex items-center gap-1 h-6 pl-2 pr-1 rounded-full bg-[color:var(--surface-muted)] text-[11px]"
            >
              {item}
              <button
                type="button"
                aria-label={`Remove ${item}`}
                onClick={() => onChange(items.filter((_, index) => index !== i))}
                className="text-[color:var(--muted-foreground)] hover:text-[color:var(--foreground)]"
              >
                <X size={11} strokeWidth={2.25} />
              </button>
            </span>
          ))}
        </div>
      )}
      <Input
        value={entry}
        placeholder="Type and press Enter"
        aria-label={`Add to ${field.label}`}
        onChange={(e) => setEntry(e.target.value)}
        onBlur={add}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ',') {
            e.preventDefault();
            add();
          }
        }}
        className={`${FIELD_CLASS} md:text-[13px]`}
      />
    </div>
  );
}

function JsonInput({ field, value, onChange }: LiteralInputProps) {
  const [error, setError] = useState<string | null>(null);

  return (
    <div className="space-y-1">
      <TextAreaField
        mono
        rows={4}
        value={asText(value)}
        placeholder="{ }"
        aria-label={field.label}
        onChange={() => setError(null)}
        onFlush={(text) => {
          const trimmed = text.trim();
          if (trimmed === '') {
            setError(null);
            onChange(undefined);
            return;
          }
          try {
            onChange(JSON.parse(trimmed));
            setError(null);
          } catch (e) {
            setError(e instanceof Error ? e.message : 'Invalid JSON');
          }
        }}
      />
      {error && <p className="text-[11px] text-[#D4183D]">{error}</p>}
    </div>
  );
}
