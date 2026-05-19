'use client';

import { useCallback, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useConversationsStore, useSettingsStore, useSidebarStore, useUsageStore } from '@/lib/store-provider';
import { Settings } from '@/lib/types';
import Sidebar from '@/components/sidebar';
import ChatView from '@/components/chat-view';

interface ChatLayoutProps {
  currentId: string | null;
}

export default function ChatLayout({ currentId }: ChatLayoutProps) {
  const router = useRouter();
  const {
    conversations, createConversation, addMessage, updateMessage, deleteConversation, renameConversation,
    setConversationModel,
    loaded: conversationsLoaded,
  } = useConversationsStore();
  const { settings, setSettings, loaded: settingsLoaded } = useSettingsStore();
  const { recordUsage, recentUsage, usageForConversation, window: usageWindow, setWindow: setUsageWindow } = useUsageStore();
  const conversationUsage = usageForConversation(currentId);
  const { open: sidebarOpen, toggle: toggleSidebar } = useSidebarStore();
  const ready = conversationsLoaded && settingsLoaded;
  const [settingsDialogOpen, setSettingsDialogOpen] = useState(false);

  const currentConversation = currentId
    ? conversations.find((c) => c.id === currentId) ?? null
    : null;

  const handleSelect = useCallback((id: string) => router.push(`/${id}`), [router]);
  const handleNewChat = useCallback(() => router.push('/'), [router]);

  const handleDelete = useCallback((id: string) => {
    deleteConversation(id);
    if (id === currentId) router.push('/');
  }, [deleteConversation, currentId, router]);

  const handleCreateConversation = useCallback((provider: Settings['defaultModel']['provider'], model: string) => {
    const id = createConversation(provider, model);
    router.push(`/${id}`);
    return id;
  }, [createConversation, router]);

  return (
    <div
      className={`bg-white transition-opacity duration-150 ${
        ready ? 'opacity-100' : 'opacity-0'
      }`}
      suppressHydrationWarning
    >
      <aside
        className={`fixed top-2 left-2 bottom-2 z-20 rounded-2xl overflow-hidden bg-[#FAFAFA] border border-black/[0.08] transition-[width] duration-300 ease-out ${
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
        <ChatView
          conversation={currentConversation}
          settings={settings}
          setSettings={setSettings}
          onAddMessage={addMessage}
          onUpdateMessage={updateMessage}
          onCreateConversation={handleCreateConversation}
          onRenameConversation={renameConversation}
          onSetConversationModel={setConversationModel}
          onRecordUsage={recordUsage}
          ready={ready}
        />
      </main>
    </div>
  );
}
