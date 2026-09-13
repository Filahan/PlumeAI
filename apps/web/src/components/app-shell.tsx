'use client';

import { ReactNode, useState, useEffect, useCallback } from 'react';
import { useSettingsStore } from '@/lib/store-provider';
import { NavRail } from '@/components/sidebar';

const SIDEBAR_OPEN_KEY = 'webui-sidebar-open';

interface AppShellProps {
  /** The left panel (e.g. the automations list on `/`). Pages with nothing to put there
   *  omit it and the shell renders the nav rail alone. */
  leftPanel?: ReactNode;
  /** Optional controlled state for the Settings dialog (the editor's assistant drawer
   *  opens it to point at a missing API key). */
  settingsOpen?: boolean;
  onSettingsOpenChange?: (open: boolean) => void;
  children: ReactNode;
}

export default function AppShell({
  leftPanel, settingsOpen, onSettingsOpenChange, children,
}: AppShellProps) {
  const { settings, setSettings, loaded: ready } = useSettingsStore();
  const [internalSettingsOpen, setInternalSettingsOpen] = useState(false);
  const settingsDialogOpen = settingsOpen ?? internalSettingsOpen;
  const setSettingsDialogOpen = onSettingsOpenChange ?? setInternalSettingsOpen;

  const [sidebarOpen, setSidebarOpen] = useState(true);
  useEffect(() => {
    const saved = localStorage.getItem(SIDEBAR_OPEN_KEY);
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (saved !== null) setSidebarOpen(saved === 'true');
  }, []);
  useEffect(() => {
    localStorage.setItem(SIDEBAR_OPEN_KEY, String(sidebarOpen));
  }, [sidebarOpen]);
  const toggleSidebar = useCallback(() => setSidebarOpen((v) => !v), []);

  return (
    <div
      className={`fixed inset-3 rounded-3xl bg-white border border-[color:var(--border)] overflow-hidden flex transition-opacity duration-150 ${ready ? 'opacity-100' : 'opacity-0'}`}
      suppressHydrationWarning
    >
      <NavRail
        settings={settings}
        setSettings={setSettings}
        settingsOpen={settingsDialogOpen}
        onSettingsOpenChange={setSettingsDialogOpen}
        onToggleSidebar={toggleSidebar}
      />
      {sidebarOpen && leftPanel}
      <main className="relative flex-1 flex flex-col min-w-0 overflow-hidden">
        {children}
      </main>
    </div>
  );
}
