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

/** One first-party integration in the catalog table. The Tool cell *is* the button — no
 *  stretched overlay across the row, which would swallow the `title` tooltips the Actions
 *  and Status cells carry, and nothing interactive is nested inside it. */
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
        className={`${ROW_GRID} py-3 border-b border-[color:var(--border)] transition-colors hover:bg-[color:var(--surface-muted)]`}
      >
        <button
          type="button"
          onClick={() => setOpen(true)}
          aria-label={`Open ${tool.label} settings`}
          className="flex items-center gap-3 min-w-0 self-stretch rounded-lg text-left outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--muted-foreground)]"
        >
          <ToolLogo src={tool.logoUrl} fallback="integration" />
          <span className="min-w-0">
            <span className="block truncate text-[13px] font-medium leading-[18px]">
              {tool.label}
            </span>
            <span className="block truncate text-[12px] leading-4 text-[color:var(--muted-foreground)]">
              {integrationGroup(tool.name)} · {integrationAuth(tool)}
            </span>
          </span>
        </button>

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

        <div className="flex justify-end">
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
