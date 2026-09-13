'use client';

import { useEffect, useRef, useState } from 'react';
import { AlertCircle } from 'lucide-react';
import type { McpServerView } from '@/lib/automations/types';
import { mcp } from '@/lib/api/endpoints';
import McpRowMenu from '@/components/tools/mcp-row-menu';
import RowAction from '@/components/tools/row-action';
import RowStatus from '@/components/tools/row-status';
import ToolLogo from '@/components/tools/tool-logo';
import { ROW_GRID } from '@/components/tools/row-grid';
import { apiMessage } from '@/components/tools/mcp-config';
import { mcpEndpoint, summarizeActions } from '@/components/tools/tool-meta';

/** How long a Delete click stays armed before it forgets it was clicked. */
const CONFIRM_MS = 2000;

/** One registered MCP server as a row of the tools table: what it is, whether it works,
 *  and — behind the overflow menu — refresh / enable / edit / delete. */
export default function McpServerRow({
  server,
  actionLabels,
  onChanged,
  onDeleted,
  onEdit,
}: {
  server: McpServerView;
  actionLabels: string[];
  onChanged: (next: McpServerView) => void;
  onDeleted: (id: string) => void;
  onEdit: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [armed, setArmed] = useState(false);
  const disarm = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (disarm.current !== null) window.clearTimeout(disarm.current);
    },
    []
  );

  const run = async (work: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await work();
    } catch (e) {
      setError(apiMessage(e, "That didn't work — try again."));
    } finally {
      setBusy(false);
    }
  };

  /** Closing the menu forgets an armed delete — the confirmation only means something
   *  while the control that asked for it is still on screen. */
  const closeMenu = (open: boolean) => {
    setMenuOpen(open);
    if (!open && disarm.current !== null) {
      window.clearTimeout(disarm.current);
      disarm.current = null;
      setArmed(false);
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
    setMenuOpen(false);
    void run(async () => {
      await mcp.remove(server.id);
      onDeleted(server.id);
    });
  };

  return (
    <div className="border-b border-[color:var(--border)] transition-colors hover:bg-[color:var(--surface-muted)]">
      <div className={`${ROW_GRID} py-3`}>
        <button
          type="button"
          onClick={onEdit}
          aria-label={`Edit ${server.name}`}
          className="flex items-center gap-3 min-w-0 self-stretch rounded-lg text-left outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--muted-foreground)]"
        >
          <ToolLogo fallback="mcp" />
          <span className="min-w-0">
            <span className="block truncate text-[13px] font-medium leading-[18px]">
              {server.name}
            </span>
            <span className="block truncate text-[12px] leading-4 text-[color:var(--muted-foreground)]">
              MCP · {mcpEndpoint(server)}
            </span>
          </span>
        </button>

        <div
          className="min-w-0 truncate text-[12px] text-[color:var(--muted-foreground)]"
          title={actionLabels.join(', ')}
        >
          {summarizeActions(actionLabels)}
        </div>

        <div className="min-w-0">
          {!server.enabled ? (
            <RowStatus tone="muted" label="Disabled" />
          ) : server.lastError ? (
            <RowStatus tone="danger" label="Not reachable" title={server.lastError} />
          ) : server.connected ? (
            <RowStatus tone="ok" label="Connected" />
          ) : (
            <RowStatus tone="muted" label="Not connected" />
          )}
        </div>

        <div className="flex items-center justify-end gap-1.5">
          <RowAction
            variant="quiet"
            label="Manage"
            ariaLabel={`Manage ${server.name}`}
            onClick={onEdit}
          />
          <McpRowMenu
            serverName={server.name}
            enabled={server.enabled}
            busy={busy}
            armed={armed}
            open={menuOpen}
            onOpenChange={closeMenu}
            onRefresh={() => void run(async () => onChanged(await mcp.refresh(server.id)))}
            onToggle={() =>
              void run(async () => onChanged(await mcp.setEnabled(server.id, !server.enabled)))
            }
            onEdit={onEdit}
            onDelete={onDelete}
          />
        </div>
      </div>

      {error && (
        <p className="flex items-start gap-1.5 px-4 pb-3 -mt-1 text-[11px] text-[#D4183D]">
          <AlertCircle size={12} strokeWidth={2.25} className="mt-px shrink-0" aria-hidden="true" />
          <span className="break-words">{error}</span>
        </p>
      )}
    </div>
  );
}
