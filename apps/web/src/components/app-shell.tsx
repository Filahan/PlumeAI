'use client';

import { ReactNode, useState, useEffect, useCallback } from 'react';
import { LogOut } from 'lucide-react';
import { useConversationsStore, useSettingsStore } from '@/lib/store-provider';
import { NavRail, ConversationListPanel } from '@/components/sidebar';

const SIDEBAR_OPEN_KEY = 'webui-sidebar-open';

async function signOut() {
  await fetch('/api/auth/logout', { method: 'POST' });
  // Cookie cleared → middleware will redirect to /login on the next request.
  window.location.replace('/');
}

interface AppShellProps {
  /** The currently-active conversation id, or null when not on a conversation route. */
  currentId: string | null;
  onSelect: (id: string) => void;
  onNewChat: () => void;
  onDelete: (id: string) => void;
  /** Replaces the conversation list in the left panel (e.g. the task list on /automations). */
  leftPanel?: ReactNode;
  children: ReactNode;
}

export default function AppShell({ currentId, onSelect, onNewChat, onDelete, leftPanel, children }: AppShellProps) {
  const { conversations, loaded: conversationsLoaded } = useConversationsStore();
  const { settings, setSettings, loaded: settingsLoaded } = useSettingsStore();
  const ready = conversationsLoaded && settingsLoaded;
  const [settingsDialogOpen, setSettingsDialogOpen] = useState(false);

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
        onNewChat={onNewChat}
        onToggleSidebar={toggleSidebar}
      />
      {sidebarOpen && (leftPanel ?? (
        <ConversationListPanel
          conversations={conversations}
          currentId={currentId}
          onSelect={onSelect}
          onDelete={onDelete}
          ready={ready}
        />
      ))}
      <main className="relative flex-1 flex flex-col min-w-0 overflow-hidden">
        <button
          type="button"
          onClick={signOut}
          aria-label="Sign out"
          className="absolute top-3 right-3 z-10 inline-flex items-center gap-1.5 h-8 px-3 rounded-full text-[12px] font-medium text-[color:var(--muted-foreground)] hover:bg-[color:var(--surface-muted)] hover:text-[color:var(--foreground)] transition-colors"
        >
          <LogOut size={14} strokeWidth={1.75} />
          Sign out
        </button>
        {children}
      </main>
    </div>
  );
}
