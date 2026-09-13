'use client';

import { useCallback } from 'react';
import { Settings } from '@/lib/types';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter,
} from '@/components/ui/dialog';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip';
import { Button } from '@/components/ui/button';
import SettingsContent from '@/components/settings-content';
import {
  Activity, Workflow, Plug, PanelLeftClose, PanelLeftOpen,
  Settings as SettingsIcon, type LucideIcon,
} from 'lucide-react';
import { useRouter, usePathname } from 'next/navigation';

interface NavRailProps {
  settings: Settings;
  setSettings: (s: Settings) => void;
  settingsOpen: boolean;
  onSettingsOpenChange: (open: boolean) => void;
  onToggleSidebar: () => void;
  /** Whether the left panel is currently showing. Drives the toggle's icon and tint. */
  sidebarOpen: boolean;
  /** False on pages that have no left panel — the toggle is hidden there, since there
   *  would be nothing to open. */
  hasLeftPanel: boolean;
}

function RailIcon({ icon: Icon, label, onClick, active }: {
  icon: LucideIcon; label: string; onClick?: () => void; active?: boolean;
}) {
  return (
    <Tooltip>
      <TooltipTrigger render={(props) => (
        <button
          {...props}
          type="button"
          onClick={onClick}
          aria-label={label}
          className={`w-10 h-10 rounded-xl flex items-center justify-center transition-colors ${
            active ? 'bg-[color:var(--surface-muted)] text-[color:var(--foreground)]' : 'text-[color:var(--muted-foreground)] hover:bg-[color:var(--surface-muted)] hover:text-[color:var(--foreground)]'
          }`}
        >
          <Icon size={18} strokeWidth={1.75} />
        </button>
      )} />
      <TooltipContent side="right" sideOffset={8}>{label}</TooltipContent>
    </Tooltip>
  );
}

export function NavRail({
  settings, setSettings, settingsOpen, onSettingsOpenChange,
  onToggleSidebar, sidebarOpen, hasLeftPanel,
}: NavRailProps) {
  const router = useRouter();
  const pathname = usePathname();
  const handleOpenSettings = useCallback(() => onSettingsOpenChange(true), [onSettingsOpenChange]);

  return (
    <>
      <aside className="w-[72px] shrink-0 h-full flex flex-col items-center bg-white border-r border-[color:var(--border)] py-3">
        <button
          type="button"
          onClick={() => router.push('/')}
          aria-label="PlumeAI — automations"
          className="w-10 h-10 rounded-xl flex items-center justify-center hover:bg-[color:var(--surface-muted)] transition-colors"
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/logo.png" alt="" className="h-6 w-auto" />
        </button>

        {hasLeftPanel && (
          <div className="mt-1">
            <RailIcon
              icon={sidebarOpen ? PanelLeftClose : PanelLeftOpen}
              label={sidebarOpen ? 'Hide automations list' : 'Show automations list'}
              active={sidebarOpen}
              onClick={onToggleSidebar}
            />
          </div>
        )}

        <div className="w-8 border-t border-[color:var(--border)] my-2" />

        <div className="flex flex-col gap-1">
          <RailIcon
            icon={Workflow}
            label="Automations"
            active={pathname === '/' || pathname.startsWith('/automations')}
            onClick={() => router.push('/')}
          />
          <RailIcon icon={Plug} label="Tools" active={pathname === '/tools'} onClick={() => router.push('/tools')} />
          <RailIcon icon={Activity} label="Usage" active={pathname === '/usage'} onClick={() => router.push('/usage')} />
        </div>

        <div className="flex-1" />

        <RailIcon icon={SettingsIcon} label="Settings" onClick={handleOpenSettings} />
      </aside>

      <Dialog open={settingsOpen} onOpenChange={onSettingsOpenChange}>
        <DialogContent className="sm:max-w-[520px] rounded-[24px] bg-white border-[color:var(--border)] shadow-2xl p-6 max-h-[85vh] overflow-y-auto">
          <DialogHeader className="space-y-1.5 pb-1">
            <DialogTitle className="text-[17px] font-semibold tracking-tight">Settings</DialogTitle>
            <DialogDescription className="text-[13px] text-[color:var(--muted-foreground)]">
              Configure your LLM providers and pick a default model.
            </DialogDescription>
          </DialogHeader>
          <div className="py-4">
            <SettingsContent settings={settings} setSettings={setSettings} variant="dialog" />
          </div>
          <DialogFooter className="gap-2 pt-3 border-t border-[color:var(--border)]">
            <Button
              onClick={() => onSettingsOpenChange(false)}
              className="h-9 px-4 rounded-xl bg-[color:var(--primary)] text-white text-[13px] font-medium hover:opacity-90"
            >
              Done
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
