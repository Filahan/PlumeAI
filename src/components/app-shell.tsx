'use client';

import { ReactNode, useCallback, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useConversationsStore, useSettingsStore, useSidebarStore, useUsageStore } from '@/lib/store-provider';
import Sidebar from '@/components/sidebar';

interface AppShellProps {
  /** The currently-active conversation id, or null when not on a conversation route. */
  currentId: string | null;
  children: ReactNode;
}

export default function AppShell({ currentId, children }: AppShellProps) {
  const router = useRouter();
  const { conversations, deleteConversation, loaded: conversationsLoaded } = useConversationsStore();
  const { settings, setSettings, loaded: settingsLoaded } = useSettingsStore();
  const { recentUsage, usageForConversation, window: usageWindow, setWindow: setUsageWindow } = useUsageStore();
  const { open: sidebarOpen, toggle: toggleSidebar } = useSidebarStore();
  const ready = conversationsLoaded && settingsLoaded;
  const [settingsDialogOpen, setSettingsDialogOpen] = useState(false);

  const conversationUsage = usageForConversation(currentId);

  const handleSelect = useCallback((id: string) => router.push(`/${id}`), [router]);
  const handleNewChat = useCallback(() => router.push('/'), [router]);
  const handleDelete = useCallback((id: string) => {
    deleteConversation(id);
    if (id === currentId) router.push('/');
  }, [deleteConversation, currentId, router]);

  return (
    <div
      className={`bg-white transition-opacity duration-150 ${ready ? 'opacity-100' : 'opacity-0'}`}
      suppressHydrationWarning
    >
      <aside
        className={`fixed top-2 left-2 bottom-2 z-20 rounded-2xl overflow-hidden bg-[#F5F5F5] border border-black/[0.08] transition-[width] duration-300 ease-out ${
          sidebarOpen ? 'w-[300px]' : 'w-[72px]'
        }`}
      >
        <Sidebar
          conversations={conversations}
          currentId={currentId}
          onSelect={handleSelect}
          onNewChat={handleNewChat}
          onDelete={handleDelete}
          settings={settings}
          setSettings={setSettings}
          open={sidebarOpen}
          onToggle={toggleSidebar}
          ready={ready}
          usage={recentUsage}
          conversationUsage={conversationUsage}
          usageWindow={usageWindow}
          onUsageWindowChange={setUsageWindow}
          settingsOpen={settingsDialogOpen}
          onSettingsOpenChange={setSettingsDialogOpen}
        />
      </aside>

      <main
        className={`min-h-screen flex flex-col transition-[margin-left,width] duration-300 ease-out ${
          sidebarOpen ? 'ml-[316px] w-[calc(100vw-316px)]' : 'ml-[88px] w-[calc(100vw-88px)]'
        }`}
      >
        {children}
      </main>
    </div>
  );
}
