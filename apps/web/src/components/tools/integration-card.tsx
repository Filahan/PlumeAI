'use client';

import { useState } from 'react';
import { Check, ChevronRight, Plug } from 'lucide-react';
import type { Settings } from '@/lib/types';
import type { CatalogIntegration } from '@/lib/automations/types';
import { Dialog } from '@/components/ui/dialog';
import IntegrationModal from '@/components/tools/integration-modal';
import { isToolConnected } from '@/components/tools/connection';

/** One row of the integrations list: identity, action count, connection state. The whole
 *  row is the trigger for the setup sheet. */
export default function IntegrationCard({
  tool,
  settings,
  setSettings,
}: {
  tool: CatalogIntegration;
  settings: Settings;
  setSettings: (s: Settings) => void;
}) {
  const [open, setOpen] = useState(false);
  const connected = isToolConnected(tool, settings);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label={`Open ${tool.label} settings`}
        className="w-full flex items-center gap-3 px-4 py-3 rounded-2xl border border-[color:var(--border)] bg-white hover:bg-[color:var(--surface-muted)]/60 transition text-left"
      >
        <div className="w-10 h-10 rounded-xl bg-white border border-[color:var(--border)] flex items-center justify-center shrink-0 overflow-hidden">
          {tool.logoUrl ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={tool.logoUrl} alt={`${tool.label} logo`} className="w-5 h-5 object-contain" />
          ) : (
            <Plug size={18} strokeWidth={1.75} className="text-[color:var(--muted-foreground)]" />
          )}
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-[14px] font-medium truncate">{tool.label}</div>
          <div className="text-[12px] text-[color:var(--muted-foreground)] truncate">{tool.description}</div>
          <div className="text-[11px] text-[color:var(--muted-foreground)] mt-0.5 flex items-center gap-1.5">
            <span className="font-mono">@{tool.name}</span>
            <span>·</span>
            <span>
              {tool.actions.length} {tool.actions.length === 1 ? 'action' : 'actions'}
            </span>
          </div>
        </div>
        {connected ? (
          <span className="inline-flex items-center gap-1 text-[12px] text-[#10A37F] font-medium">
            <Check size={13} strokeWidth={2.5} /> Connected
          </span>
        ) : (
          <span className="inline-flex items-center h-9 px-4 rounded-xl bg-[color:var(--primary)] text-white text-[13px] font-medium">
            Connect
          </span>
        )}
        <ChevronRight size={14} strokeWidth={1.75} className="text-[color:var(--muted-foreground)] shrink-0" />
      </button>

      <IntegrationModal
        tool={tool}
        settings={settings}
        setSettings={setSettings}
        close={() => setOpen(false)}
      />
    </Dialog>
  );
}
