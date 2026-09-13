'use client';

import { MCP_SERVER_NAME_RE } from '@/lib/automations/types';
import { NAME_HINT } from '@/components/tools/mcp-config';

/** The server's slug, with the rule stated under the field as you type.
 *
 *  The hint is the same sentence the API's own rejection is rewritten into, so a name the
 *  form let through and the server refused never explains itself two different ways. */
export default function McpNameField({
  value,
  onChange,
}: {
  value: string;
  onChange: (next: string) => void;
}) {
  const trimmed = value.trim();
  const invalid = trimmed.length > 0 && !MCP_SERVER_NAME_RE.test(trimmed);

  return (
    <div>
      <label
        htmlFor="mcp-name"
        className="block text-[11px] font-medium text-[color:var(--foreground)] mb-1"
      >
        Name
      </label>
      <input
        id="mcp-name"
        value={value}
        onChange={(e) => onChange(e.target.value.toLowerCase())}
        placeholder="notion"
        autoComplete="off"
        spellCheck={false}
        aria-invalid={invalid}
        aria-describedby="mcp-name-hint"
        className="w-full h-9 rounded-lg border border-[color:var(--border)] bg-white px-2.5 text-[12px] font-mono outline-none placeholder:text-[#A8A8B0] focus:border-[#111111] focus:ring-2 focus:ring-black/5 transition"
      />
      <p
        id="mcp-name-hint"
        className={`mt-1 text-[10px] leading-relaxed ${
          invalid ? 'text-[#D4183D]' : 'text-[color:var(--muted-foreground)]'
        }`}
      >
        {NAME_HINT}
      </p>
    </div>
  );
}
