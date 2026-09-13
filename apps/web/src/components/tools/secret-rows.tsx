'use client';

import { Plus, RotateCcw, X } from 'lucide-react';
import { withRow, type SecretRow } from '@/components/tools/mcp-config';

const INPUT =
  'h-8 rounded-lg border border-[color:var(--border)] bg-white px-2 text-[12px] outline-none placeholder:text-[#A8A8B0] focus:border-[#111111] focus:ring-2 focus:ring-black/5 transition';

/** Key/value editor for write-only secrets (stdio `env`, http `headers`).
 *
 *  A row whose value is already stored renders as "set" — the API never returns it — with
 *  Replace as the only way to type a new one. */
export default function SecretRows({
  label,
  hint,
  valuePlaceholder,
  rows,
  onChange,
}: {
  label: string;
  hint: string;
  valuePlaceholder: string;
  rows: SecretRow[];
  onChange: (next: SecretRow[]) => void;
}) {
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2 mb-1">
        <span className="text-[11px] font-medium text-[color:var(--foreground)]">{label}</span>
        <span className="text-[10px] text-[color:var(--muted-foreground)]">{hint}</span>
      </div>

      <div className="space-y-1.5">
        {rows.map((row, i) => (
          <div key={i} className="flex items-center gap-1.5">
            <input
              value={row.key}
              onChange={(e) => onChange(withRow(rows, i, { key: e.target.value }))}
              placeholder="NAME"
              aria-label={`${label} name`}
              autoComplete="off"
              spellCheck={false}
              className={`${INPUT} w-[40%] font-mono`}
            />
            {row.saved && row.value.length === 0 ? (
              <button
                type="button"
                onClick={() => onChange(withRow(rows, i, { saved: false }))}
                className="flex-1 h-8 inline-flex items-center justify-between gap-1.5 rounded-lg border border-[color:var(--border)] bg-[color:var(--surface-muted)]/60 px-2 text-[11px] text-[color:var(--muted-foreground)] hover:text-[color:var(--foreground)] transition"
              >
                <span className="inline-flex items-center gap-1.5">
                  <span className="rounded px-1 py-px bg-[#10A37F]/10 text-[#10A37F] font-medium">set</span>
                  <span className="font-mono tracking-widest">••••••</span>
                </span>
                <span className="inline-flex items-center gap-1">
                  <RotateCcw size={11} strokeWidth={2} /> Replace
                </span>
              </button>
            ) : (
              <input
                type="password"
                value={row.value}
                onChange={(e) => onChange(withRow(rows, i, { value: e.target.value }))}
                placeholder={valuePlaceholder}
                aria-label={`${label} value`}
                autoComplete="off"
                spellCheck={false}
                className={`${INPUT} flex-1`}
              />
            )}
            <button
              type="button"
              onClick={() => onChange(rows.filter((_, j) => j !== i))}
              aria-label={`Remove ${row.key || 'row'}`}
              className="h-8 w-8 shrink-0 inline-flex items-center justify-center rounded-lg text-[color:var(--muted-foreground)] hover:bg-[color:var(--surface-muted)] hover:text-[color:var(--foreground)] transition"
            >
              <X size={13} strokeWidth={2} />
            </button>
          </div>
        ))}
      </div>

      <button
        type="button"
        onClick={() => onChange([...rows, { key: '', value: '', saved: false }])}
        className="mt-1.5 inline-flex items-center gap-1 h-7 px-2 rounded-lg border border-dashed border-[color:var(--border)] text-[11px] font-medium text-[color:var(--muted-foreground)] hover:text-[color:var(--foreground)] hover:bg-[color:var(--surface-muted)] transition"
      >
        <Plus size={12} strokeWidth={2} /> Add {label.toLowerCase().replace(/s$/, '')}
      </button>
    </div>
  );
}
