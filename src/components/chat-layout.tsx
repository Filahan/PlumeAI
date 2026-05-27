'use client';

import { useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { useConversationsStore, useSettingsStore, useUsageStore } from '@/lib/store-provider';
import { Provider } from '@/lib/types';
import AppShell from '@/components/app-shell';
import ChatView from '@/components/chat-view';

interface ChatLayoutProps {
  currentId: string | null;
}

export default function ChatLayout({ currentId }: ChatLayoutProps) {
  const router = useRouter();
  const {
    conversations, createConversation, addMessage, updateMessage, renameConversation, setConversationModel,
    loaded: conversationsLoaded,
  } = useConversationsStore();
  const { settings, loaded: settingsLoaded } = useSettingsStore();
  const { recordUsage } = useUsageStore();
  const ready = conversationsLoaded && settingsLoaded;

  const currentConversation = currentId
    ? conversations.find((c) => c.id === currentId) ?? null
    : null;

  const handleCreateConversation = useCallback((provider: Provider, model: string) => {
    const id = createConversation(provider, model);
    router.push(`/${id}`);
    return id;
  }, [createConversation, router]);

  return (
    <AppShell currentId={currentId}>
      <ChatView
        conversation={currentConversation}
        settings={settings}
        onAddMessage={addMessage}
        onUpdateMessage={updateMessage}
        onCreateConversation={handleCreateConversation}
        onRenameConversation={renameConversation}
        onSetConversationModel={setConversationModel}
        onRecordUsage={recordUsage}
        ready={ready}
      />
    </AppShell>
  );
}
