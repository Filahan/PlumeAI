import type { CatalogIntegration, McpServerView } from '@/lib/automations/types';

/** Which family a first-party integration belongs to, for the row's sub-line. Unknown
 *  names fall back to a generic word rather than guessing. */
const GROUPS: Record<string, string> = {
  gmail: 'Google Workspace',
  drive: 'Google Workspace',
  calendar: 'Google Workspace',
  slack: 'Messaging',
  discord: 'Messaging',
  notion: 'Docs & notes',
};

export function integrationGroup(name: string): string {
  return GROUPS[name] ?? 'Integration';
}

/** How you authenticate, in two or three words. Credential labels carry a parenthetical
 *  hint about the token format ("Bot token (xoxb-…)") that the sub-line doesn't need. */
export function integrationAuth(tool: CatalogIntegration): string {
  if (tool.connectMode === 'oauth') return 'OAuth';
  const fields = tool.credentialsFields ?? [];
  if (fields.length === 1) {
    const label = fields[0].label.replace(/\s*\(.*\)\s*$/, '').trim();
    if (label) return label;
  }
  return 'API key';
}

/** Where an MCP server lives: the command line for stdio, the URL for http. */
export function mcpEndpoint(server: McpServerView): string {
  if (server.transport === 'http') return server.url ?? 'http';
  return [server.command ?? '', ...server.args].join(' ').trim() || 'stdio';
}

/** "Search emails, Get an email, +4" — the Actions cell truncates, and the full list
 *  lives in the cell's `title`. */
export function summarizeActions(labels: string[]): string {
  if (labels.length === 0) return 'No actions yet';
  const extra = labels.length - 2;
  const head = labels.slice(0, 2).join(', ');
  return extra > 0 ? `${head}, +${extra}` : head;
}
