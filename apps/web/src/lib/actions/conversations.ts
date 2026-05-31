/** Thin client-side wrappers around the FastAPI conversations endpoints. */

import { api } from '@/lib/api-client';
import type { Conversation, Message, Provider } from '@/lib/types';

export async function listConversations(): Promise<Conversation[]> {
  return api.get<Conversation[]>('/conversations');
}

export async function createConversation(
  id: string,
  provider: Provider,
  model: string
): Promise<void> {
  await api.post('/conversations', { id, provider, model });
}

export async function addMessage(
  conversationId: string,
  message: Omit<Message, 'timestamp'>
): Promise<{ firstUserMessage: boolean }> {
  return api.post<{ firstUserMessage: boolean }>(
    `/conversations/${encodeURIComponent(conversationId)}/messages`,
    {
      id: message.id,
      role: message.role,
      content: message.content,
      ...(message.attachments ? { attachments: message.attachments } : {}),
    }
  );
}

export async function updateMessage(
  conversationId: string,
  messageId: string,
  chunk: string,
  replace = false
): Promise<void> {
  await api.patch(
    `/conversations/${encodeURIComponent(conversationId)}/messages/${encodeURIComponent(messageId)}`,
    { chunk, replace }
  );
}

export async function renameConversation(id: string, title: string): Promise<void> {
  if (!title) return;
  await api.patch(`/conversations/${encodeURIComponent(id)}`, { title });
}

export async function setConversationModel(
  id: string,
  provider: Provider,
  model: string
): Promise<void> {
  await api.patch(`/conversations/${encodeURIComponent(id)}`, { provider, model });
}

export async function deleteConversation(id: string): Promise<void> {
  await api.delete(`/conversations/${encodeURIComponent(id)}`);
}
