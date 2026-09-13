'use client';

import { Bot, Filter, Globe, Server, Zap } from 'lucide-react';
import { useCatalog } from '@/lib/automations/store';
import {
  BUILTIN_INTEGRATION,
  MCP_INTEGRATION_PREFIX,
  findCatalogIntegration,
} from '@/lib/automations/types';

export type NodeIconKind = 'trigger' | 'action' | 'ai' | 'filter';

const FALLBACK = { trigger: Zap, action: Globe, ai: Bot, filter: Filter } as const;

/** The square glyph on the left of every canvas node: the integration's own logo when
 *  the catalog knows one, a lucide glyph otherwise (builtin actions, AI, filters and
 *  the trigger never have a logo). MCP servers have no logo either — nothing about a
 *  `mcp:<server>` tool tells us what it looks like — so they get their own glyph rather
 *  than the generic action globe. */
export default function NodeIcon({
  kind,
  integration,
}: {
  kind: NodeIconKind;
  integration?: string;
}) {
  const catalog = useCatalog();
  const isMcp = !!integration && integration.startsWith(MCP_INTEGRATION_PREFIX);
  const logoUrl =
    kind === 'action' && integration && integration !== BUILTIN_INTEGRATION && !isMcp
      ? findCatalogIntegration(catalog, integration)?.logoUrl || null
      : null;
  const Fallback = isMcp && kind === 'action' ? Server : FALLBACK[kind];

  return (
    <span className="w-8 h-8 shrink-0 rounded-xl border border-[color:var(--border)] bg-white flex items-center justify-center overflow-hidden">
      {logoUrl ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={logoUrl} alt="" className="w-4 h-4 object-contain" />
      ) : (
        <Fallback
          size={15}
          strokeWidth={1.75}
          className="text-[color:var(--muted-foreground)]"
          aria-hidden="true"
        />
      )}
    </span>
  );
}
