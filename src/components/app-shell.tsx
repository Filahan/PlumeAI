'use client';

import { ReactNode, useCallback, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useConversationsStore, useSettingsStore, useSidebarStore } from '@/lib/store-provider';
import { NavRail, ConversationListPanel } from '@/components/sidebar';

interface AppShellProps {
  /** The currently-active conversation id, or null when not on a conversation route. */
  currentId: string | null;
  children: ReactNode;
}

export default function AppShell({ currentId, children }: AppShellProps) {
  const router = useRouter();
  const { conversations, deleteConversation, loaded: conversationsLoaded } = useConversationsStore();
  const { settings, setSettings, loaded: settingsLoaded } = useSettingsStore();
  const { open: sidebarOpen, toggle: toggleSidebar } = useSidebarStore();
  const ready = conversationsLoaded && settingsLoaded;
  const [settingsDialogOpen, setSettingsDialogOpen] = useState(false);

  const handleSelect = useCallback((id: string) => router.push(`/${id}`), [router]);
  const handleNewChat = useCallback(() => router.push('/'), [router]);
  const handleDelete = useCallback((id: string) => {
    deleteConversation(id);
    if (id === currentId) router.push('/');
  }, [deleteConversation, currentId, router]);

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
        onNewChat={handleNewChat}
        onToggleSidebar={toggleSidebar}
      />
      {sidebarOpen && (
        <ConversationListPanel
          conversations={conversations}
          currentId={currentId}
          onSelect={handleSelect}
          onNewChat={handleNewChat}
          onDelete={handleDelete}
          ready={ready}
        />
      )}
      <main className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {children}
      </main>
    </div>
  );
}
