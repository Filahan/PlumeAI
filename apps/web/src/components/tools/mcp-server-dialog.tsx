'use client';

import { useState } from 'react';
import { AlertCircle, Loader2 } from 'lucide-react';
import {
  MCP_SERVER_NAME_RE,
  type McpServerConfigInput,
  type McpServerView,
  type McpTestResult,
  type McpTransport,
} from '@/lib/automations/types';
import { mcp } from '@/lib/api/endpoints';
import { DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import McpTestResultPanel from '@/components/tools/mcp-test-result';
import McpTransportFields, { type TransportValues } from '@/components/tools/mcp-transport-fields';
import {
  apiMessage,
  formatArgs,
  parseArgs,
  rowsFromNames,
  secretsFromRows,
  unfilledNames,
} from '@/components/tools/mcp-config';

type Form = TransportValues & { name: string };

function initialForm(server: McpServerView | null): Form {
  return {
    name: server?.name ?? '',
    transport: server?.transport ?? 'stdio',
    command: server?.command ?? '',
    argsText: formatArgs(server?.args ?? []),
    env: rowsFromNames(server?.envNames ?? []),
    url: server?.url ?? '',
    headers: rowsFromNames(server?.headerNames ?? []),
    allowPrivateNetwork: server?.allowPrivateNetwork ?? false,
  };
}

function buildConfig(form: Form): McpServerConfigInput {
  return form.transport === 'stdio'
    ? { command: form.command.trim(), args: parseArgs(form.argsText), env: secretsFromRows(form.env) }
    : { url: form.url.trim(), headers: secretsFromRows(form.headers) };
}

/** Whether anything the *connection* depends on differs from what is stored. Only then
 *  may a PUT carry a `config` — the API replaces it wholesale, so an unnecessary one
 *  would wipe every secret the user did not retype. */
function configChanged(form: Form, server: McpServerView): boolean {
  if (form.transport !== server.transport) return true;
  const rows = form.transport === 'stdio' ? form.env : form.headers;
  const names = form.transport === 'stdio' ? server.envNames : server.headerNames;
  if (rows.some((r) => r.value.length > 0)) return true;
  if (rows.map((r) => r.key.trim()).join('\n') !== names.join('\n')) return true;
  return form.transport === 'stdio'
    ? form.command.trim() !== (server.command ?? '') ||
        parseArgs(form.argsText).join('\n') !== server.args.join('\n')
    : form.url.trim() !== (server.url ?? '');
}

/** Add or edit one MCP server. Mounted only while open, so its state starts fresh every
 *  time and needs no effect to reset. */
export default function McpServerDialog({
  server,
  onSaved,
  onClose,
}: {
  server: McpServerView | null;
  onSaved: (saved: McpServerView) => void;
  onClose: () => void;
}) {
  const [form, setForm] = useState<Form>(() => initialForm(server));
  const [test, setTest] = useState<McpTestResult | null>(null);
  const [busy, setBusy] = useState<'test' | 'save' | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Any edit invalidates the previous probe — a green "6 tools" under a changed URL lies.
  const patch = (next: Partial<Form>) => {
    setForm((prev) => ({ ...prev, ...next }));
    setTest(null);
  };

  const nameOk = MCP_SERVER_NAME_RE.test(form.name);
  const targetOk = form.transport === 'stdio' ? !!form.command.trim() : !!form.url.trim();
  const dirtyConfig = server === null || configChanged(form, server);
  const dropped = dirtyConfig ? unfilledNames(form.transport === 'stdio' ? form.env : form.headers) : [];

  const probe = async () => {
    setBusy('test');
    setError(null);
    try {
      setTest(
        await mcp.test({
          transport: form.transport,
          config: buildConfig(form),
          allowPrivateNetwork: form.allowPrivateNetwork,
        })
      );
    } catch (e) {
      setError(apiMessage(e, "That config couldn't be tested."));
    } finally {
      setBusy(null);
    }
  };

  const save = async () => {
    setBusy('save');
    setError(null);
    try {
      const saved =
        server === null
          ? await mcp.create({
              name: form.name,
              transport: form.transport,
              config: buildConfig(form),
              allowPrivateNetwork: form.allowPrivateNetwork,
            })
          : await mcp.update(server.id, {
              name: form.name,
              transport: form.transport,
              allowPrivateNetwork: form.allowPrivateNetwork,
              ...(dirtyConfig ? { config: buildConfig(form) } : {}),
            });
      onSaved(saved);
      onClose();
    } catch (e) {
      setError(apiMessage(e, "That server couldn't be saved."));
    } finally {
      setBusy(null);
    }
  };

  return (
    <DialogContent className="sm:max-w-[560px]">
      <DialogHeader>
        <DialogTitle>{server ? `Edit ${server.name}` : 'Add MCP server'}</DialogTitle>
        <DialogDescription>
          Its tools become steps you can use in automations, under <code className="font-mono">mcp:{form.name || '<name>'}</code>.
        </DialogDescription>
      </DialogHeader>

      <div className="overflow-y-auto max-h-[60vh] space-y-4 pr-1">
        <div>
          <label htmlFor="mcp-name" className="block text-[11px] font-medium text-[color:var(--foreground)] mb-1">
            Name
          </label>
          <input
            id="mcp-name"
            value={form.name}
            onChange={(e) => patch({ name: e.target.value.toLowerCase() })}
            placeholder="notion"
            autoComplete="off"
            spellCheck={false}
            aria-invalid={form.name.length > 0 && !nameOk}
            className="w-full h-9 rounded-lg border border-[color:var(--border)] bg-white px-2.5 text-[12px] font-mono outline-none placeholder:text-[#A8A8B0] focus:border-[#111111] focus:ring-2 focus:ring-black/5 transition"
          />
          <p
            className={`mt-1 text-[10px] leading-relaxed ${
              form.name.length > 0 && !nameOk ? 'text-[#D4183D]' : 'text-[color:var(--muted-foreground)]'
            }`}
          >
            2–31 characters: lowercase letters, digits, <code className="font-mono">-</code> or{' '}
            <code className="font-mono">_</code>, starting with a letter or digit.
          </p>
        </div>

        <div>
          <span className="block text-[11px] font-medium text-[color:var(--foreground)] mb-1">Transport</span>
          <div role="radiogroup" aria-label="Transport" className="inline-flex rounded-xl border border-[color:var(--border)] bg-[color:var(--surface-muted)]/50 p-0.5">
            {(['stdio', 'http'] as McpTransport[]).map((t) => (
              <button
                key={t}
                type="button"
                role="radio"
                aria-checked={form.transport === t}
                onClick={() => patch({ transport: t })}
                className={`h-7 px-3 rounded-lg text-[12px] font-medium transition ${
                  form.transport === t
                    ? 'bg-white text-[color:var(--foreground)] shadow-[0_1px_2px_rgba(0,0,0,0.06)]'
                    : 'text-[color:var(--muted-foreground)] hover:text-[color:var(--foreground)]'
                }`}
              >
                {t === 'stdio' ? 'Command (stdio)' : 'URL (http)'}
              </button>
            ))}
          </div>
        </div>

        <McpTransportFields values={form} onChange={patch} />

        {dropped.length > 0 && (
          <p className="rounded-lg border border-[#b45309]/30 bg-[#b45309]/5 px-3 py-2 text-[11px] text-[#b45309] leading-relaxed">
            Saving replaces the whole connection config, so the stored value of{' '}
            <span className="font-mono">{dropped.join(', ')}</span> will be removed. Use Replace to type
            it again if the server still needs it.
          </p>
        )}

        {test && <McpTestResultPanel result={test} />}

        {error && (
          <p className="flex items-start gap-1.5 rounded-lg border border-[#D4183D]/30 bg-[#D4183D]/5 px-3 py-2 text-[12px] text-[#D4183D]">
            <AlertCircle size={13} strokeWidth={2.25} className="mt-px shrink-0" />
            <span className="break-words">{error}</span>
          </p>
        )}
      </div>

      <div className="flex items-center justify-between gap-2 pt-3 mt-1 border-t border-[color:var(--border)] -mx-4 px-4">
        <button
          type="button"
          onClick={probe}
          disabled={busy !== null || !targetOk}
          className="h-9 px-3 inline-flex items-center gap-1.5 rounded-xl border border-[color:var(--border)] bg-white text-[13px] font-medium hover:bg-[color:var(--surface-muted)] transition disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {busy === 'test' && <Loader2 size={14} className="animate-spin" />}
          Test connection
        </button>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onClose}
            className="h-9 px-3 rounded-xl text-[13px] font-medium text-[color:var(--muted-foreground)] hover:text-[color:var(--foreground)] transition"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={save}
            disabled={busy !== null || !nameOk || !targetOk}
            className="h-9 px-4 inline-flex items-center gap-1.5 rounded-xl bg-[color:var(--primary)] text-white text-[13px] font-medium hover:opacity-90 transition disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {busy === 'save' && <Loader2 size={14} className="animate-spin" />}
            {server ? 'Save changes' : 'Add server'}
          </button>
        </div>
      </div>
    </DialogContent>
  );
}
