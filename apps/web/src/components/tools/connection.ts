import type { Settings } from '@/lib/types';
import type { CatalogIntegration } from '@/lib/automations/types';

/** Connection state for one integration.
 *
 *  The catalog already reports `connected` server-side, but `settings` is what this view
 *  updates optimistically when you connect/disconnect — so the local signal wins when it
 *  exists and the catalog is the fallback (fresh page, tool absent from settings). */
export function isToolConnected(tool: CatalogIntegration, settings: Settings): boolean {
  if (tool.connectMode === 'config') {
    const local = tool.credentialsNamespace
      ? settings.toolCredentials?.[tool.credentialsNamespace]
      : undefined;
    return local ?? tool.connected;
  }
  return settings.tools?.[tool.name]?.connected ?? tool.connected;
}
