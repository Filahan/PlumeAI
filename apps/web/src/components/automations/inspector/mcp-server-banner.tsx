'use client';

import { useRouter } from 'next/navigation';
import { Server } from 'lucide-react';
import type { CatalogMcpServer } from '@/lib/automations/types';

/** Shown above an MCP action's settings while its server cannot serve it.
 *
 *  It has to come *before* the "this action no longer exists" path: a disabled server is
 *  published with an empty action list, so the catalog genuinely cannot resolve the step's
 *  action — but the honest explanation is "you turned this server off", not "this action
 *  is gone". */
export default function McpServerBanner({ server }: { server: CatalogMcpServer }) {
  const router = useRouter();
  const disabled = !server.enabled;

  return (
    <div className="rounded-xl border border-[#b45309]/30 bg-[#b45309]/5 px-3 py-2.5">
      <div className="flex items-start gap-2">
        <Server size={13} strokeWidth={2} className="mt-0.5 shrink-0 text-[#b45309]" />
        <div className="min-w-0 flex-1">
          <p className="text-[12px] font-medium text-[#b45309]">
            {disabled
              ? `${server.name} is disabled`
              : `${server.name} isn't reachable`}
          </p>
          <p className="text-[11px] text-[#b45309]/80 break-words">
            {disabled
              ? 'Turn it back on from the Tools page so this step can run.'
              : server.lastError || 'The server did not answer the last time it was synced.'}
          </p>
        </div>
        <button
          type="button"
          onClick={() => router.push('/tools')}
          className="shrink-0 h-7 px-2.5 rounded-lg bg-[color:var(--primary)] text-white text-[11px] font-medium hover:opacity-90 transition"
        >
          Open Tools
        </button>
      </div>
    </div>
  );
}
