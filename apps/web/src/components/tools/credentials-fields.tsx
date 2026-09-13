'use client';

import { useState } from 'react';
import { Check, Eye, EyeOff } from 'lucide-react';
import type { CredentialField } from '@/lib/automations/types';

/** The token half of an integration's setup.
 *
 *  Saved credentials are never read back, so the section collapses to a "Saved" badge
 *  with an Edit affordance instead of pretending to show the stored value. */
export default function CredentialsFields({
  toolName,
  fields,
  values,
  onChange,
  saved,
}: {
  toolName: string;
  fields: CredentialField[];
  values: Record<string, string>;
  onChange: (next: Record<string, string>) => void;
  saved: boolean;
}) {
  const [reveal, setReveal] = useState<Record<string, boolean>>({});
  const [editing, setEditing] = useState(!saved);

  return (
    <section className="rounded-xl border border-[color:var(--border)] bg-[color:var(--surface-muted)]/40 p-3">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-[color:var(--muted-foreground)] flex items-center gap-1.5">
          Credentials
          {saved && !editing && (
            <span className="inline-flex items-center gap-1 text-[#10A37F] font-medium normal-case tracking-normal">
              <Check size={12} strokeWidth={2.5} /> Saved
            </span>
          )}
        </h3>
        {saved && (
          <button
            type="button"
            onClick={() => setEditing((v) => !v)}
            className="text-[11px] font-medium text-[color:var(--muted-foreground)] hover:text-[color:var(--foreground)] transition"
          >
            {editing ? 'Cancel' : 'Edit'}
          </button>
        )}
      </div>

      {(editing || !saved) && (
        <div className="space-y-2">
          {fields.map((f) => {
            const shown = !f.secret || !!reveal[f.name];
            return (
              <div key={f.name}>
                <label
                  htmlFor={`cred-${toolName}-${f.name}`}
                  className="block text-[11px] font-medium text-[color:var(--foreground)] mb-1"
                >
                  {f.label}
                </label>
                <div className="relative">
                  <input
                    id={`cred-${toolName}-${f.name}`}
                    type={shown ? 'text' : 'password'}
                    value={values[f.name] ?? ''}
                    onChange={(e) => onChange({ ...values, [f.name]: e.target.value })}
                    placeholder={f.placeholder}
                    autoComplete="off"
                    spellCheck={false}
                    className="w-full h-9 rounded-lg border border-[color:var(--border)] bg-white pl-2.5 pr-9 text-[12px] outline-none placeholder:text-[#A8A8B0] focus:border-[#111111] focus:ring-2 focus:ring-black/5 transition"
                  />
                  {f.secret && (
                    <button
                      type="button"
                      onClick={() => setReveal({ ...reveal, [f.name]: !reveal[f.name] })}
                      tabIndex={-1}
                      aria-label={shown ? 'Hide' : 'Show'}
                      className="absolute right-2 top-1/2 -translate-y-1/2 text-[color:var(--muted-foreground)] hover:text-[#111111] transition-colors"
                    >
                      {shown ? <EyeOff size={14} /> : <Eye size={14} />}
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
