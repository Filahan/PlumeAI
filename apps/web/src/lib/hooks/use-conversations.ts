'use client';

import { useCallback, useEffect, useState } from 'react';
import { Conversation, Message, Provider } from '@/lib/types';
import { conversations as convsApi } from '@/lib/api';
import { deleteBlobs } from '@/lib/blob-store';

function newId(): string {
  return crypto.randomUUID();
}

export function useConversations() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    convsApi
      .list()
      .then((rows) => {
        if (!cancelled) setConversations(rows);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const createConversation = useCallback((provider: Provider, model: string) => {
    const id = newId();
    const now = Date.now();
    const conv: Conversation = {
      id,
      title: 'Nouvelle conversation',
      messages: [],
      createdAt: now,
      updatedAt: now,
      provider,
      model,
    };
    setConversations((prev) => [conv, ...prev]);
    convsApi.create(id, provider, model).catch(() => {
      setConversations((prev) => prev.filter((c) => c.id !== id));
    });
    return id;
  }, []);

  const addMessage = useCallback(
    (conversationId: string, message: Omit<Message, 'id' | 'timestamp'>) => {
      const id = newId();
      const now = Date.now();
      const msg: Message = { ...message, id, timestamp: now };
      setConversations((prev) =>
        prev.map((c) => {
          if (c.id !== conversationId) return c;
          const isFirstUserMessage = c.messages.length === 0 && msg.role === 'user';
          return {
            ...c,
            messages: [...c.messages, msg],
            title: isFirstUserMessage
              ? message.content.slice(0, 40) + (message.content.length > 40 ? '...' : '')
              : c.title,
            updatedAt: now,
          };
        })
      );
      convsApi.addMessage(conversationId, { ...message, id }).catch(() => {});
      return id;
    },
    []
  );

  const updateMessage = useCallback(
    (conversationId: string, messageId: string, chunk: string, replace = false) => {
      setConversations((prev) =>
        prev.map((c) => {
          if (c.id !== conversationId) return c;
          return {
            ...c,
            messages: c.messages.map((m) =>
              m.id === messageId ? { ...m, content: replace ? chunk : m.content + chunk } : m
            ),
            updatedAt: Date.now(),
          };
        })
      );
      convsApi.updateMessage(conversationId, messageId, chunk, replace).catch(() => {});
    },
    []
  );

  const deleteConversation = useCallback((id: string) => {
    setConversations((prev) => {
      const target = prev.find((c) => c.id === id);
      if (target) {
        const blobIds = target.messages.flatMap((m) => m.attachments?.map((a) => a.id) ?? []);
        if (blobIds.length > 0) deleteBlobs(blobIds).catch(() => {});
      }
      return prev.filter((c) => c.id !== id);
    });
    convsApi.delete(id).catch(() => {});
  }, []);

  const renameConversation = useCallback((id: string, title: string) => {
    if (!title) return;
    setConversations((prev) =>
      prev.map((c) => (c.id === id ? { ...c, title, updatedAt: Date.now() } : c))
    );
    convsApi.rename(id, title).catch(() => {});
  }, []);

  const setConversationModel = useCallback(
    (id: string, provider: Provider, model: string) => {
      setConversations((prev) =>
        prev.map((c) => (c.id === id ? { ...c, provider, model, updatedAt: Date.now() } : c))
      );
      convsApi.setModel(id, provider, model).catch(() => {});
    },
    []
  );

  return {
    conversations,
    createConversation,
    addMessage,
    updateMessage,
    deleteConversation,
    renameConversation,
    setConversationModel,
    loaded,
  };
}
