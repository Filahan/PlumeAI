'use client';

import { useEffect, useRef, useState } from 'react';
import { AlertCircle, Check, Loader2, Pencil, RefreshCw, Trash2 } from 'lucide-react';
import type { McpServerView } from '@/lib/automations/types';
import { mcp } from '@/lib/api/endpoints';
import { Switch } from '@/components/ui/switch';
import { apiMessage } from '@/components/tools/mcp-config';

/** Tool names shown before the list collapses into "+n". */
const CHIP_LIMIT = 6;
/** How long a Delete click stays armed before it forgets it was clicked. */
const CONFIRM_MS = 2000;

type Busy = 'refresh' | 'toggle' | 'delete' | null;

function IconButton({
  label,
  onClick,
  disabled,
  danger,
  children,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  danger?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      title={label}
      className={`h-8 w-8 inline-flex items-center justify-center rounded-lg border border-[color:var(--border)] bg-white transition disabled:opacity-40 disabled:cursor-not-allowed ${
        danger
          ? 'text-[color:var(--muted-foreground)] hover:bg-[#D4183D]/5 hover:text-[#D4183D] hover:border-[#D4183D]/30'
          : 'text-[color:var(--muted-foreground)] hover:bg-[color:var(--surface-muted)] hover:text-[color:var(--foreground)]'
      }`}
    >
      {children}
    </button>
  );
}

/** One registered MCP server: what it is, whether it works, and what its tools are called. */
export default function McpServerCard({
  server,
  onChanged,
  onDeleted,
  onEdit,
}: {
  server: McpServerView;
  onChanged: (next: McpServerView) => void;
  onDeleted: (id: string) => void;
  onEdit: () => void;
}) {
  const [busy, setBusy] = useState<Busy>(null);
  const [error, setError] = useState<string | null>(null);
  const [armed, setArmed] = useState(false);
  const disarm = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (disarm.current !== null) window.clearTimeout(disarm.current);
    },
    []
  );

  const run = async (kind: Exclude<Busy, null>, work: () => Promise<void>) => {
    setBusy(kind);
    setError(null);
    try {
      await work();
    } catch (e) {
      setError(apiMessage(e, "That didn't work — try again."));
    } finally {
      setBusy(null);
    }
  };

  const onDelete = () => {
    if (!armed) {
      setArmed(true);
      disarm.current = window.setTimeout(() => setArmed(false), CONFIRM_MS);
      return;
    }
    if (disarm.current !== null) window.clearTimeout(disarm.current);
    setArmed(false);
    void run('delete', async () => {
      await mcp.remove(server.id);
      onDeleted(server.id);
    });
  };

  const chips = server.tools.slice(0, CHIP_LIMIT);
  const extra = server.tools.length - chips.length;

  return (
    <div className="rounded-2xl border border-[color:var(--border)] bg-white px-4 py-3">
      <div className="flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[14px] font-medium truncate">{server.name}</span>
            <span className="rounded-md border border-[color:var(--border)] bg-[color:var(--surface-muted)] px-1.5 py-px text-[10px] font-mono text-[color:var(--muted-foreground)]">
              {server.transport}
            </span>
          </div>

          <div className="mt-0.5 text-[12px]">
            {!server.enabled ? (
              <span className="text-[color:var(--muted-foreground)]">Disabled</span>
            ) : server.lastError ? (
              <span className="flex items-start gap-1.5 text-[#D4183D]">
                <AlertCircle size={13} strokeWidth={2.25} className="mt-px shrink-0" />
                <span className="break-words">{server.lastError}</span>
              </span>
            ) : server.connected ? (
              <span className="inline-flex items-center gap-1 text-[#10A37F] font-medium">
                <Check size={13} strokeWidth={2.5} /> Connected · {server.toolCount}{' '}
                {server.toolCount === 1 ? 'tool' : 'tools'}
              </span>
            ) : (
              <span className="text-[color:var(--muted-foreground)]">
                No tools yet — refresh to sync.
              </span>
            )}
          </div>

          {chips.length > 0 && (
            <div className="mt-1.5 flex flex-wrap gap-1">
              {chips.map((tool) => (
                <span
                  key={tool.name}
                  title={tool.description || undefined}
                  className="rounded-md border border-[color:var(--border)] bg-[color:var(--surface-muted)]/60 px-1.5 py-px font-mono text-[10px] text-[color:var(--muted-foreground)]"
                >
                  {tool.name}
                </span>
              ))}
              {extra > 0 && (
                <span className="px-1 py-px text-[10px] text-[color:var(--muted-foreground)]">
                  +{extra}
                </span>
              )}
            </div>
          )}
        </div>

        <div className="flex items-center gap-1.5 shrink-0">
          <Switch
            checked={server.enabled}
            disabled={busy !== null}
            onCheckedChange={(next) =>
              void run('toggle', async () => onChanged(await mcp.setEnabled(server.id, next)))
            }
            aria-label={server.enabled ? `Disable ${server.name}` : `Enable ${server.name}`}
            className="mr-1"
          />
          <IconButton
            label="Refresh tools"
            disabled={busy !== null || !server.enabled}
            onClick={() =>
              void run('refresh', async () => onChanged(await mcp.refresh(server.id)))
            }
          >
            {busy === 'refresh' ? (
              <Loader2 size={13} className="animate-spin" />
            ) : (
              <RefreshCw size={13} strokeWidth={2} />
            )}
          </IconButton>
          <IconButton label="Edit server" disabled={busy !== null} onClick={onEdit}>
            <Pencil size={13} strokeWidth={2} />
          </IconButton>
          {armed ? (
            <button
              type="button"
              onClick={onDelete}
              className="h-8 px-2.5 rounded-lg border border-[#D4183D]/30 bg-[#D4183D]/5 text-[11px] font-medium text-[#D4183D] hover:bg-[#D4183D]/10 transition"
            >
              Confirm
            </button>
          ) : (
            <IconButton label="Delete server" danger disabled={busy !== null} onClick={onDelete}>
              {busy === 'delete' ? (
                <Loader2 size={13} className="animate-spin" />
              ) : (
                <Trash2 size={13} strokeWidth={2} />
              )}
            </IconButton>
          )}
        </div>
      </div>

      {error && (
        <p className="mt-2 flex items-start gap-1.5 text-[11px] text-[#D4183D]">
          <AlertCircle size={12} strokeWidth={2.25} className="mt-px shrink-0" />
          <span className="break-words">{error}</span>
        </p>
      )}
    </div>
  );
}
