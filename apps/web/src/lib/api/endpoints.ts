/** Typed wrappers for every FastAPI endpoint, grouped by domain.
 *
 *  Usage:
 *      import { settings, conversations, automations, usage, chat } from '@/lib/api';
 *      const all = await conversations.list();
 *      const res = await chat.stream(req, signal);
 *
 *  SSE endpoints return a raw `Response` — combine with `parseSSE<Event>` from `./sse`.
 */

import { api } from './client';
import type {
  Conversation,
  Message,
  Provider,
  Settings,
  Task,
  TaskSchedule,
  TaskStatus,
  UsageEntry,
} from '@/lib/types';

// ─── Settings + tools ───────────────────────────────────────────────────────────────

export const settings = {
  get: () => api.get<Settings>('/settings'),
  update: (next: Settings) => api.put<Settings>('/settings', next),
  disconnectTool: (name: string) =>
    api.post(`/tools/${encodeURIComponent(name)}/disconnect`),
};

// ─── Conversations ──────────────────────────────────────────────────────────────────

export const conversations = {
  list: () => api.get<Conversation[]>('/conversations'),

  create: (id: string, provider: Provider, model: string) =>
    api.post('/conversations', { id, provider, model }),

  addMessage: (
    conversationId: string,
    message: Omit<Message, 'timestamp'>
  ): Promise<{ firstUserMessage: boolean }> =>
    api.post<{ firstUserMessage: boolean }>(
      `/conversations/${encodeURIComponent(conversationId)}/messages`,
      {
        id: message.id,
        role: message.role,
        content: message.content,
        ...(message.attachments ? { attachments: message.attachments } : {}),
      }
    ),

  updateMessage: (
    conversationId: string,
    messageId: string,
    chunk: string,
    replace = false
  ): Promise<void> =>
    api.patch(
      `/conversations/${encodeURIComponent(conversationId)}/messages/${encodeURIComponent(messageId)}`,
      { chunk, replace }
    ),

  rename: (id: string, title: string): Promise<void> =>
    title ? api.patch(`/conversations/${encodeURIComponent(id)}`, { title }) : Promise.resolve(),

  setModel: (id: string, provider: Provider, model: string): Promise<void> =>
    api.patch(`/conversations/${encodeURIComponent(id)}`, { provider, model }),

  delete: (id: string): Promise<void> =>
    api.delete(`/conversations/${encodeURIComponent(id)}`),
};

// ─── Automations ────────────────────────────────────────────────────────────────────

interface UpdateTaskPatch {
  title?: string;
  prompt?: string;
  schedule?: TaskSchedule;
  status?: TaskStatus;
  output?: string;
  error?: string | null;
  provider?: Provider;
  model?: string;
}

export const automations = {
  list: () => api.get<Task[]>('/automations'),

  create: (
    id: string,
    prompt: string,
    schedule: TaskSchedule,
    provider: Provider,
    model: string
  ) => api.post('/automations', { id, prompt, schedule, provider, model }),

  update: (id: string, patch: UpdateTaskPatch) =>
    api.patch(`/automations/${encodeURIComponent(id)}`, patch),

  delete: (id: string) => api.delete(`/automations/${encodeURIComponent(id)}`),

  chat: (taskId: string, message: string) =>
    api.post<{
      question?: string;
      options?: string[];
      finalized?: boolean;
      skill?: string;
      title?: string;
    }>('/automations/chat', { taskId, message }),

  runStream: (taskId: string, signal?: AbortSignal) =>
    api.sse('/automations/run', { taskId }, signal),
};

// ─── Usage ──────────────────────────────────────────────────────────────────────────

export const usage = {
  list: () => api.get<UsageEntry[]>('/usage'),
};

// ─── Chat (raw streaming) ───────────────────────────────────────────────────────────

export type ContentPart =
  | { type: 'text'; text: string }
  | { type: 'image'; mime: string; base64: string };
export type ChatContent = string | ContentPart[];

export interface ChatStreamRequest {
  provider: Provider;
  model: string;
  history: Array<{ role: 'user' | 'assistant'; content: ChatContent }>;
  newMessage: ChatContent;
  conversationId?: string | null;
}

export const chat = {
  stream: (req: ChatStreamRequest, signal?: AbortSignal) =>
    api.sse('/chat/stream', req, signal),
};
