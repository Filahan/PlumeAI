'use client';

import { ShieldAlert } from 'lucide-react';
import type { McpTransport } from '@/lib/automations/types';
import SecretRows from '@/components/tools/secret-rows';
import type { SecretRow } from '@/components/tools/mcp-config';

const FIELD =
  'w-full h-9 rounded-lg border border-[color:var(--border)] bg-white px-2.5 text-[12px] outline-none placeholder:text-[#A8A8B0] focus:border-[#111111] focus:ring-2 focus:ring-black/5 transition';

function Label({ htmlFor, children }: { htmlFor: string; children: React.ReactNode }) {
  return (
    <label htmlFor={htmlFor} className="block text-[11px] font-medium text-[color:var(--foreground)] mb-1">
      {children}
    </label>
  );
}

export interface TransportValues {
  transport: McpTransport;
  command: string;
  argsText: string;
  env: SecretRow[];
  url: string;
  headers: SecretRow[];
  allowPrivateNetwork: boolean;
}

/** Everything about *how* to reach a server — the half of the form that swaps wholesale
 *  when the transport changes. */
export default function McpTransportFields({
  values,
  onChange,
}: {
  values: TransportValues;
  onChange: (patch: Partial<TransportValues>) => void;
}) {
  if (values.transport === 'stdio') {
    return (
      <div className="space-y-3">
        <div>
          <Label htmlFor="mcp-command">Command</Label>
          <input
            id="mcp-command"
            value={values.command}
            onChange={(e) => onChange({ command: e.target.value })}
            placeholder="uvx"
            autoComplete="off"
            spellCheck={false}
            className={`${FIELD} font-mono`}
          />
          <p className="mt-1 text-[10px] text-[color:var(--muted-foreground)] leading-relaxed">
            The command runs inside the PlumeAI API container, so only what is installed there
            works — <code className="font-mono">uvx …</code> and <code className="font-mono">python …</code>.
            There is no <code className="font-mono">npx</code>.
          </p>
        </div>

        <div>
          <Label htmlFor="mcp-args">Arguments</Label>
          <textarea
            id="mcp-args"
            value={values.argsText}
            onChange={(e) => onChange({ argsText: e.target.value })}
            rows={3}
            placeholder={'mcp-server-time\n--local-timezone=Europe/Paris'}
            spellCheck={false}
            className="w-full rounded-lg border border-[color:var(--border)] bg-white px-2.5 py-2 text-[12px] font-mono outline-none placeholder:text-[#A8A8B0] focus:border-[#111111] focus:ring-2 focus:ring-black/5 transition resize-y"
          />
          <p className="mt-1 text-[10px] text-[color:var(--muted-foreground)]">
            One per line, or a single line of space-separated arguments.
          </p>
        </div>

        <SecretRows
          label="Environment variables"
          hint="values are write-only"
          valuePlaceholder="value"
          rows={values.env}
          onChange={(env) => onChange({ env })}
        />
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div>
        <Label htmlFor="mcp-url">URL</Label>
        <input
          id="mcp-url"
          value={values.url}
          onChange={(e) => onChange({ url: e.target.value })}
          placeholder="https://example.com/mcp"
          autoComplete="off"
          spellCheck={false}
          inputMode="url"
          className={`${FIELD} font-mono`}
        />
      </div>

      <SecretRows
        label="Headers"
        hint="values are write-only"
        valuePlaceholder="value"
        rows={values.headers}
        onChange={(headers) => onChange({ headers })}
      />

      <label className="flex items-start gap-2 rounded-xl border border-[color:var(--border)] bg-[color:var(--surface-muted)]/40 p-2.5 cursor-pointer">
        <input
          type="checkbox"
          checked={values.allowPrivateNetwork}
          onChange={(e) => onChange({ allowPrivateNetwork: e.target.checked })}
          className="mt-0.5 size-3.5 shrink-0 accent-[#111111]"
        />
        <span className="min-w-0">
          <span className="block text-[12px] font-medium text-[color:var(--foreground)]">
            Allow private network
          </span>
          <span className="mt-0.5 flex items-start gap-1 text-[10px] text-[color:var(--muted-foreground)] leading-relaxed">
            <ShieldAlert size={11} strokeWidth={2} className="mt-px shrink-0 text-[#b45309]" />
            <span>
              Off, the URL must be a public address. On, PlumeAI will also connect to localhost and
              private ranges — which lets a URL you got from someone else reach services inside your
              network. Only enable it for a server you run yourself.
            </span>
          </span>
        </span>
      </label>
    </div>
  );
}
