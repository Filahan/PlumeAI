'use client';

import { useState } from 'react';
import type { Settings } from '@/lib/types';
import type { CatalogIntegration } from '@/lib/automations/types';
import { Dialog } from '@/components/ui/dialog';
import IntegrationModal from '@/components/tools/integration-modal';
import RowAction from '@/components/tools/row-action';
import RowStatus from '@/components/tools/row-status';
import ToolLogo from '@/components/tools/tool-logo';
import { ROW_GRID } from '@/components/tools/row-grid';
import {
  integrationAuth,
  integrationGroup,
  summarizeActions,
} from '@/components/tools/tool-meta';

/** One first-party integration in the catalog table. The name is the row's real button
 *  and its `::after` stretches over the whole row, so clicking anywhere but the right
 *  cell opens the setup sheet without nesting one control inside another. */
export default function IntegrationRow({
  tool,
  connected,
  actionLabels,
  settings,
  setSettings,
}: {
  tool: CatalogIntegration;
  connected: boolean;
  actionLabels: string[];
  settings: Settings;
  setSettings: (s: Settings) => void;
}) {
  const [open, setOpen] = useState(false);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <div
        className={`${ROW_GRID} relative py-3 border-b border-[color:var(--border)] transition-colors hover:bg-[color:var(--surface-muted)]`}
      >
        <div className="flex items-center gap-3 min-w-0">
          <ToolLogo src={tool.logoUrl} fallback="integration" />
          <div className="min-w-0">
            <button
              type="button"
              onClick={() => setOpen(true)}
              aria-label={`Open ${tool.label} settings`}
              className="block max-w-full truncate rounded-sm text-left text-[13px] font-medium leading-[18px] outline-none after:absolute after:inset-0 after:content-[''] focus-visible:ring-2 focus-visible:ring-[color:var(--muted-foreground)]"
            >
              {tool.label}
            </button>
            <div className="truncate text-[12px] leading-4 text-[color:var(--muted-foreground)]">
              {integrationGroup(tool.name)} · {integrationAuth(tool)}
            </div>
          </div>
        </div>

        <div
          className="min-w-0 truncate text-[12px] text-[color:var(--muted-foreground)]"
          title={actionLabels.join(', ')}
        >
          {summarizeActions(actionLabels)}
        </div>

        <div className="min-w-0">
          {connected ? (
            <RowStatus tone="ok" label="Connected" />
          ) : (
            <RowStatus tone="muted" label="Not connected" />
          )}
        </div>

        <div className="relative flex justify-end">
          <RowAction
            variant={connected ? 'quiet' : 'outline'}
            label={connected ? 'Manage' : 'Connect'}
            ariaLabel={connected ? `Manage ${tool.label}` : `Connect ${tool.label}`}
            onClick={() => setOpen(true)}
          />
        </div>
      </div>

      <IntegrationModal
        tool={tool}
        settings={settings}
        setSettings={setSettings}
        close={() => setOpen(false)}
      />
    </Dialog>
  );
}
