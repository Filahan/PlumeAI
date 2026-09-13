'use client';

import { useSearchParams } from 'next/navigation';
import { AlertCircle, Plug } from 'lucide-react';
import type { Settings } from '@/lib/types';
import { useCatalog } from '@/lib/automations/store';
import IntegrationCard from '@/components/tools/integration-card';
import McpServersSection from '@/components/tools/mcp-servers-section';

/** The Tools page: first-party integrations you connect with an account, then any MCP
 *  server you bring yourself. Both end up in the same catalog the step picker reads. */
export default function ToolsView({
  settings,
  setSettings,
}: {
  settings: Settings;
  setSettings: (s: Settings) => void;
}) {
  const params = useSearchParams();
  const catalog = useCatalog();
  const errorMessage =
    params.get('status') === 'error' ? params.get('message') : null;

  return (
    <div className="w-full max-w-[760px] mx-auto px-8 py-8 overflow-y-auto h-full">
      <div className="mb-6">
        <h1 className="text-[20px] font-semibold tracking-tight flex items-center gap-2">
          <Plug size={18} strokeWidth={1.75} /> Tools
        </h1>
        <p className="text-[11px] text-[color:var(--muted-foreground)]">
          Connect external accounts so your automations can call them. Tokens are encrypted at rest.
        </p>
      </div>

      {errorMessage && (
        <div className="mb-4 rounded-xl border border-[#D4183D]/30 bg-[#D4183D]/5 px-3.5 py-2.5 flex items-start gap-2 text-[12px] text-[#D4183D]">
          <AlertCircle size={14} strokeWidth={2.25} className="shrink-0 mt-0.5" />
          <span>
            <strong>Connection error:</strong> {errorMessage}. Reopen the tool to review setup.
          </span>
        </div>
      )}

      <div className="space-y-2">
        {catalog === null ? (
          <p className="text-[12px] text-[color:var(--muted-foreground)]">Loading tools…</p>
        ) : (
          catalog.integrations.map((t) => (
            <IntegrationCard key={t.name} tool={t} settings={settings} setSettings={setSettings} />
          ))
        )}
      </div>

      <McpServersSection />
    </div>
  );
}
