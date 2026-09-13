'use client';

import { useCallback, useEffect, useState } from 'react';
import type { McpServerView } from '@/lib/automations/types';
import { mcp, tools as toolsApi } from '@/lib/api/endpoints';
import { useAutomationsStore } from '@/lib/automations/store';
import { apiMessage } from '@/components/tools/mcp-config';

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

export interface McpServersState {
  /** `null` while the first listing is still in flight. */
  servers: McpServerView[] | null;
  error: string | null;
  /** One server's row was rewritten by the API — take its answer as the new truth. */
  replace: (next: McpServerView) => void;
  remove: (id: string) => void;
}

/** Loads the registered MCP servers and keeps the cached catalog in step with any write
 *  a row makes. Owning this here lets the Tools page mix servers and integrations into
 *  one table without the two halves knowing about each other. */
export function useMcpServers(): McpServersState {
  const [servers, setServers] = useState<McpServerView[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    mcp
      .list()
      .then((list) => {
        if (cancelled) return;
        setServers(list);
        setError(null);
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

  /** A write that got through also clears whatever the last failure was saying. */
  const replace = useCallback((next: McpServerView) => {
    setServers((prev) => {
      const rest = (prev ?? []).filter((s) => s.id !== next.id);
      return [...rest, next].sort((a, b) => a.name.localeCompare(b.name));
    });
    setError(null);
    void reloadCatalog();
  }, []);

  const remove = useCallback((id: string) => {
    setServers((prev) => (prev ?? []).filter((s) => s.id !== id));
    setError(null);
    void reloadCatalog();
  }, []);

  return { servers, error, replace, remove };
}
