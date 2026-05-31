import 'server-only';

import { eq } from 'drizzle-orm';
import { db } from '@/lib/db';
import { settings } from '@/lib/db/schema';
import type { Tool, ToolSchema } from '@/lib/tools/types';
import { gmailTool } from '@/lib/tools/gmail';

/** Server-side registry of available tools, keyed by `tool.name`. */
export const TOOLS: Record<string, Tool> = {
  [gmailTool.name]: gmailTool,
};

/** Map function name → owning tool (e.g. 'gmail_search' → gmailTool). */
export function findToolForFunction(fnName: string): Tool | undefined {
  for (const tool of Object.values(TOOLS)) {
    if (tool.schemas.some((s) => s.function.name === fnName)) return tool;
  }
  return undefined;
}

/** Tools currently configured (e.g. OAuth tokens present). Used by the agent + interviewer. */
export async function listConfiguredTools(): Promise<Tool[]> {
  const entries = await Promise.all(
    Object.values(TOOLS).map(async (t) => ({ tool: t, ok: await t.isConfigured() }))
  );
  return entries.filter((e) => e.ok).map((e) => e.tool);
}

/** Aggregate function schemas from configured tools (for inclusion in the agent's toolset). */
export async function listConfiguredToolSchemas(): Promise<ToolSchema[]> {
  const tools = await listConfiguredTools();
  return tools.flatMap((t) => t.schemas);
}

/** Connection metadata view of all tools, safe to send to the client (no secrets). */
export async function getToolConnections(): Promise<Record<string, { connected: boolean }>> {
  const out: Record<string, { connected: boolean }> = {};
  for (const tool of Object.values(TOOLS)) {
    out[tool.name] = { connected: await tool.isConfigured() };
  }
  return out;
}

/** Remove a tool's stored credentials. */
export async function clearToolCreds(toolName: string): Promise<void> {
  const [row] = await db.select().from(settings).where(eq(settings.id, 1));
  if (!row) return;
  const next = { ...row.tools };
  delete next[toolName];
  await db.update(settings).set({ tools: next }).where(eq(settings.id, 1));
}
