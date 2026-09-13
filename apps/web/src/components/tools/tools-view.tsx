'use client';

import { useMemo, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { AlertCircle, Plus } from 'lucide-react';
import type { Settings } from '@/lib/types';
import type { McpServerView } from '@/lib/automations/types';
import { useCatalog } from '@/lib/automations/store';
import { Dialog } from '@/components/ui/dialog';
import IntegrationRow from '@/components/tools/integration-row';
import McpServerDialog from '@/components/tools/mcp-server-dialog';
import McpServerRow from '@/components/tools/mcp-server-row';
import ToolsTable from '@/components/tools/tools-table';
import ToolsToolbar from '@/components/tools/tools-toolbar';
import {
  buildToolEntries,
  filterToolEntries,
  toolCounts,
  type ToolFilter,
} from '@/components/tools/tool-entries';
import { useMcpServers } from '@/components/tools/use-mcp-servers';

/** `'new'` is the add dialog, a server is the edit dialog, `null` is closed. */
type Editing = McpServerView | 'new' | null;

/** The Tools page: one catalog of everything an automation can call — the first-party
 *  integrations you connect with an account, and any MCP server you brought yourself. */
export default function ToolsView({
  settings,
  setSettings,
}: {
  settings: Settings;
  setSettings: (s: Settings) => void;
}) {
  const params = useSearchParams();
  const catalog = useCatalog();
  const { servers, error: mcpError, replace, remove } = useMcpServers();
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState<ToolFilter>('all');
  const [editing, setEditing] = useState<Editing>(null);

  const errorMessage = params.get('status') === 'error' ? params.get('message') : null;

  const entries = useMemo(
    () => buildToolEntries(catalog, settings, servers),
    [catalog, settings, servers]
  );
  const visible = useMemo(
    () => filterToolEntries(entries, query, filter),
    [entries, query, filter]
  );
  const counts = toolCounts(visible);
  const loading = catalog === null || servers === null;
  const filtered = query.trim() !== '' || filter !== 'all';

  return (
    <div className="w-full max-w-[960px] mx-auto px-8 py-8 overflow-y-auto h-full">
      <div className="flex items-end justify-between gap-4 mb-5">
        <div className="min-w-0">
          <h1 className="text-[20px] font-semibold tracking-[-0.02em] leading-7">Tools</h1>
          <p className="text-[13px] text-[color:var(--muted-foreground)] leading-5 mt-1.5">
            Accounts and servers your automations can use.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setEditing('new')}
          className="shrink-0 h-8 px-3 inline-flex items-center gap-1.5 rounded-[10px] bg-[color:var(--primary)] text-[color:var(--primary-foreground)] text-[13px] font-medium whitespace-nowrap transition hover:opacity-90"
        >
          <Plus size={14} strokeWidth={2} aria-hidden="true" /> Add MCP server
        </button>
      </div>

      {errorMessage && (
        <div className="mb-4 rounded-xl border border-[#D4183D]/30 bg-[#D4183D]/5 px-3.5 py-2.5 flex items-start gap-2 text-[12px] text-[#D4183D]">
          <AlertCircle size={14} strokeWidth={2.25} className="shrink-0 mt-0.5" aria-hidden="true" />
          <span>
            <strong>Connection error:</strong> {errorMessage}. Reopen the tool to review setup.
          </span>
        </div>
      )}

      {mcpError && (
        <p className="mb-4 flex items-start gap-1.5 rounded-xl border border-[#D4183D]/30 bg-[#D4183D]/5 px-3.5 py-2.5 text-[12px] text-[#D4183D]">
          <AlertCircle size={14} strokeWidth={2.25} className="mt-px shrink-0" aria-hidden="true" />
          <span className="break-words">{mcpError}</span>
        </p>
      )}

      <div className="mb-4">
        <ToolsToolbar
          query={query}
          onQueryChange={setQuery}
          filter={filter}
          onFilterChange={setFilter}
        />
      </div>

      <ToolsTable>
        {loading && visible.length === 0 ? (
          <p className="px-4 py-8 text-center text-[12px] text-[color:var(--muted-foreground)]">
            Loading tools…
          </p>
        ) : visible.length === 0 ? (
          <div className="px-4 py-8 text-center text-[12px] text-[color:var(--muted-foreground)]">
            No tool matches {query.trim() ? `“${query.trim()}”` : 'this filter'}.
            {filtered && (
              <button
                type="button"
                onClick={() => {
                  setQuery('');
                  setFilter('all');
                }}
                className="ml-1.5 font-medium text-[color:var(--foreground)] underline underline-offset-2"
              >
                Clear filters
              </button>
            )}
          </div>
        ) : (
          visible.map((entry) =>
            entry.kind === 'integration' ? (
              <IntegrationRow
                key={entry.key}
                tool={entry.tool}
                connected={entry.connected}
                actionLabels={entry.actionLabels}
                settings={settings}
                setSettings={setSettings}
              />
            ) : (
              <McpServerRow
                key={entry.key}
                server={entry.server}
                actionLabels={entry.actionLabels}
                onChanged={replace}
                onDeleted={remove}
                onEdit={() => setEditing(entry.server)}
              />
            )
          )
        )}
      </ToolsTable>

      <p className="mt-3 px-1 text-[12px] text-[color:var(--muted-foreground)]">
        {counts.tools} {counts.tools === 1 ? 'tool' : 'tools'} · {counts.connected} connected ·{' '}
        {counts.actions} {counts.actions === 1 ? 'action' : 'actions'} available to your automations
      </p>
      <p className="mt-1 px-1 text-[12px] text-[color:var(--muted-foreground)]">
        Bring your own tools: any MCP server’s tools become steps in your automations.
      </p>

      <Dialog open={editing !== null} onOpenChange={(open) => !open && setEditing(null)}>
        {editing !== null && (
          <McpServerDialog
            server={editing === 'new' ? null : editing}
            onSaved={replace}
            onClose={() => setEditing(null)}
          />
        )}
      </Dialog>
    </div>
  );
}
