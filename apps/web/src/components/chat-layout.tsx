'use client';

import { useCallback, useEffect, useState } from 'react';
import { useConversationsStore, useSettingsStore, useUsageStore } from '@/lib/store-provider';
import { Provider } from '@/lib/types';
import AppShell from '@/components/app-shell';
import ChatView from '@/components/chat/view';

function pathnameToId(p: string): string | null {
  return p === '/' ? null : p.slice(1) || null;
}

export default function ChatLayout() {
  // Active id mirrors the URL but updates via history.pushState so ChatView's
  // local state survives between `/` and `/{id}`. router.push would remount it.
  const [activeId, setActiveIdRaw] = useState<string | null>(() =>
    typeof window === 'undefined' ? null : pathnameToId(window.location.pathname)
  );

  const setActiveId = useCallback((id: string | null) => {
    setActiveIdRaw(id);
    const url = id ? `/${id}` : '/';
    if (window.location.pathname !== url) {
      window.history.pushState(null, '', url);
    }
  }, []);

  useEffect(() => {
    const onPop = () => setActiveIdRaw(pathnameToId(window.location.pathname));
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);

  const {
    conversations, createConversation, deleteConversation, addMessage, updateMessage,
    renameConversation, setConversationModel, loaded: conversationsLoaded,
  } = useConversationsStore();
  const { settings, loaded: settingsLoaded } = useSettingsStore();
  const { recordUsage } = useUsageStore();
  const ready = conversationsLoaded && settingsLoaded;

  const currentConversation = activeId
    ? conversations.find((c) => c.id === activeId) ?? null
    : null;

  const handleCreateConversation = useCallback((provider: Provider, model: string) => {
    const id = createConversation(provider, model);
    setActiveId(id);
    return id;
  }, [createConversation, setActiveId]);

  const handleSelect = useCallback((id: string) => setActiveId(id), [setActiveId]);
  const handleNewChat = useCallback(() => setActiveId(null), [setActiveId]);
  const handleDelete = useCallback((id: string) => {
    deleteConversation(id);
    if (id === activeId) setActiveId(null);
  }, [deleteConversation, activeId, setActiveId]);

  return (
    <AppShell
      currentId={activeId}
      onSelect={handleSelect}
      onNewChat={handleNewChat}
      onDelete={handleDelete}
    >
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
