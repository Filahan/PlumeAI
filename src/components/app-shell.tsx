'use client';

import { ReactNode, useState } from 'react';
import { useConversationsStore, useSettingsStore, useSidebarStore } from '@/lib/store-provider';
import { NavRail, ConversationListPanel } from '@/components/sidebar';

interface AppShellProps {
  /** The currently-active conversation id, or null when not on a conversation route. */
  currentId: string | null;
  onSelect: (id: string) => void;
  onNewChat: () => void;
  onDelete: (id: string) => void;
  children: ReactNode;
}

export default function AppShell({ currentId, onSelect, onNewChat, onDelete, children }: AppShellProps) {
  const { conversations, loaded: conversationsLoaded } = useConversationsStore();
  const { settings, setSettings, loaded: settingsLoaded } = useSettingsStore();
  const { open: sidebarOpen, toggle: toggleSidebar } = useSidebarStore();
  const ready = conversationsLoaded && settingsLoaded;
  const [settingsDialogOpen, setSettingsDialogOpen] = useState(false);

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
      {sidebarOpen && (
        <ConversationListPanel
          conversations={conversations}
          currentId={currentId}
          onSelect={onSelect}
          onNewChat={onNewChat}
          onDelete={onDelete}
          ready={ready}
        />
      )}
      <main className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {children}
      </main>
    </div>
  );
}
