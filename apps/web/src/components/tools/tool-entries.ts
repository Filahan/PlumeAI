import type { Settings } from '@/lib/types';
import type { Catalog, CatalogIntegration, McpServerView } from '@/lib/automations/types';
import { isToolConnected } from '@/components/tools/connection';
import { mcpEndpoint } from '@/components/tools/tool-meta';

export type ToolFilter = 'all' | 'connected' | 'disconnected' | 'mcp';

export const TOOL_FILTERS: { id: ToolFilter; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'connected', label: 'Connected' },
  { id: 'disconnected', label: 'Not connected' },
  { id: 'mcp', label: 'MCP' },
];

/** One line of the table, whichever half of the page it came from. `search` is the
 *  pre-lowercased haystack so filtering never rebuilds it per keystroke per row. */
export type ToolEntry =
  | {
      kind: 'integration';
      key: string;
      connected: boolean;
      actionLabels: string[];
      search: string;
      tool: CatalogIntegration;
    }
  | {
      kind: 'mcp';
      key: string;
      connected: boolean;
      actionLabels: string[];
      search: string;
      server: McpServerView;
    };

function haystack(parts: (string | null | undefined)[]): string {
  return parts.filter(Boolean).join(' ').toLowerCase();
}

/** Integrations first (catalog order), then MCP servers — the catalog is the source of
 *  truth for which integrations exist, `servers` for what you brought yourself. */
export function buildToolEntries(
  catalog: Catalog | null,
  settings: Settings,
  servers: McpServerView[] | null
): ToolEntry[] {
  const integrations = (catalog?.integrations ?? []).map((tool): ToolEntry => {
    const actionLabels = tool.actions.map((a) => a.label);
    return {
      kind: 'integration',
      key: `integration:${tool.name}`,
      connected: isToolConnected(tool, settings),
      actionLabels,
      search: haystack([
        tool.label,
        tool.name,
        tool.description,
        ...actionLabels,
        ...tool.actions.map((a) => a.name),
      ]),
      tool,
    };
  });

  const mcpRows = (servers ?? []).map((server): ToolEntry => {
    const actionLabels = server.tools.map((t) => t.name);
    return {
      kind: 'mcp',
      key: `mcp:${server.id}`,
      connected: server.enabled && server.connected,
      actionLabels,
      search: haystack([
        server.name,
        'mcp',
        mcpEndpoint(server),
        ...actionLabels,
        ...server.tools.map((t) => t.description),
      ]),
      server,
    };
  });

  return [...integrations, ...mcpRows];
}

export function filterToolEntries(
  entries: ToolEntry[],
  query: string,
  filter: ToolFilter
): ToolEntry[] {
  const needle = query.trim().toLowerCase();
  return entries.filter((entry) => {
    if (filter === 'mcp' && entry.kind !== 'mcp') return false;
    if (filter === 'connected' && !entry.connected) return false;
    if (filter === 'disconnected' && entry.connected) return false;
    return needle === '' || entry.search.includes(needle);
  });
}

/** "7 tools · 3 connected · 30 actions available to your automations". */
export function toolCounts(entries: ToolEntry[]): {
  tools: number;
  connected: number;
  actions: number;
} {
  return {
    tools: entries.length,
    connected: entries.filter((e) => e.connected).length,
    actions: entries.reduce((sum, e) => sum + e.actionLabels.length, 0),
  };
}
