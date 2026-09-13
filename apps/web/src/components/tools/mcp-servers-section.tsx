'use client';

import { useEffect, useState } from 'react';
import { AlertCircle, Plus, Server } from 'lucide-react';
import type { McpServerView } from '@/lib/automations/types';
import { mcp, tools as toolsApi } from '@/lib/api/endpoints';
import { useAutomationsStore } from '@/lib/automations/store';
import { Dialog } from '@/components/ui/dialog';
import McpServerCard from '@/components/tools/mcp-server-card';
import McpServerDialog from '@/components/tools/mcp-server-dialog';
import { apiMessage } from '@/components/tools/mcp-config';

/** `'new'` is the add dialog, a server is the edit dialog, `null` is closed. */
type Editing = McpServerView | 'new' | null;

/** The catalog is fetched once per session and cached in the store, so every write here
 *  has to push the new one in — otherwise a server added on this page stays invisible to
 *  the step picker until a full reload. */
async function reloadCatalog(): Promise<void> {
  try {
    useAutomationsStore.setState({ catalog: await toolsApi.catalog() });
  } catch {
    /* the catalog only decorates other views — never block a write on it */
  }
}

export default function McpServersSection() {
  const [servers, setServers] = useState<McpServerView[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Editing>(null);

  useEffect(() => {
    let cancelled = false;
    mcp
      .list()
      .then((list) => {
        if (!cancelled) setServers(list);
      })
      .catch((e) => {
        if (cancelled) return;
        setServers([]);
        setError(apiMessage(e, "Couldn't load your MCP servers."));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  /** One server's row was rewritten by the API — take its answer as the new truth. */
  const replace = (next: McpServerView) => {
    setServers((prev) => {
      const rest = (prev ?? []).filter((s) => s.id !== next.id);
      return [...rest, next].sort((a, b) => a.name.localeCompare(b.name));
    });
    void reloadCatalog();
  };

  const remove = (id: string) => {
    setServers((prev) => (prev ?? []).filter((s) => s.id !== id));
    void reloadCatalog();
  };

  return (
    <section className="mt-10">
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="min-w-0">
          <h2 className="text-[15px] font-semibold tracking-tight flex items-center gap-2">
            <Server size={15} strokeWidth={1.75} /> Custom tools (MCP servers)
          </h2>
          <p className="text-[11px] text-[color:var(--muted-foreground)] mt-0.5">
            Connect any MCP server. Its tools become steps you can use in automations.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setEditing('new')}
          className="shrink-0 h-9 px-3 inline-flex items-center gap-1.5 rounded-xl border border-[color:var(--border)] bg-white text-[13px] font-medium hover:bg-[color:var(--surface-muted)] transition"
        >
          <Plus size={14} strokeWidth={2} /> Add MCP server
        </button>
      </div>

      {error && (
        <p className="mb-3 flex items-start gap-1.5 rounded-xl border border-[#D4183D]/30 bg-[#D4183D]/5 px-3.5 py-2.5 text-[12px] text-[#D4183D]">
          <AlertCircle size={14} strokeWidth={2.25} className="mt-px shrink-0" />
          <span className="break-words">{error}</span>
        </p>
      )}

      {servers === null ? (
        <p className="text-[12px] text-[color:var(--muted-foreground)]">Loading MCP servers…</p>
      ) : servers.length === 0 ? (
        <p className="rounded-2xl border border-dashed border-[color:var(--border)] px-4 py-6 text-center text-[12px] text-[color:var(--muted-foreground)] leading-relaxed">
          No MCP servers yet. Add one to bring its tools into the step picker and the AI step.
        </p>
      ) : (
        <div className="space-y-2">
          {servers.map((server) => (
            <McpServerCard
              key={server.id}
              server={server}
              onChanged={replace}
              onDeleted={remove}
              onEdit={() => setEditing(server)}
            />
          ))}
        </div>
      )}

      <Dialog open={editing !== null} onOpenChange={(open) => !open && setEditing(null)}>
        {editing !== null && (
          <McpServerDialog
            server={editing === 'new' ? null : editing}
            onSaved={replace}
            onClose={() => setEditing(null)}
          />
        )}
      </Dialog>
    </section>
  );
}
