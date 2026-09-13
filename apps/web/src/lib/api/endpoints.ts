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
  AutomationDetail,
  AutomationDocument,
  AutomationSummary,
  Conversation,
  DocumentWriteResult,
  Message,
  Operation,
  Provider,
  RunDetail,
  RunSummary,
  RunTrigger,
  Settings,
  UsageEntry,
} from '@/lib/types';

// ─── Settings + tools ───────────────────────────────────────────────────────────────

export const settings = {
  get: () => api.get<Settings>('/settings'),
  update: (next: Settings) => api.put<Settings>('/settings', next),
  disconnectTool: (name: string) =>
    api.post(`/tools/${encodeURIComponent(name)}/disconnect`),
  saveToolCredentials: (namespace: string, fields: Record<string, string>) =>
    api.put(`/tools/credentials/${encodeURIComponent(namespace)}`, fields),
  clearToolCredentials: (namespace: string) =>
    api.delete(`/tools/credentials/${encodeURIComponent(namespace)}`),
  discordMeta: () =>
    api.get<{
      bot_name: string | null;
      application_id: string | null;
      invite_url: string | null;
    }>('/tools/discord/meta'),
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

export const automations = {
  list: () => api.get<AutomationSummary[]>('/automations'),

  create: (body?: { name?: string; document?: AutomationDocument }) =>
    api.post<AutomationDetail>('/automations', body ?? {}),

  get: (id: string) => api.get<AutomationDetail>(`/automations/${encodeURIComponent(id)}`),

  patch: (id: string, patch: { name?: string; enabled?: boolean }) =>
    api.patch<AutomationDetail>(`/automations/${encodeURIComponent(id)}`, patch),

  remove: (id: string) => api.delete(`/automations/${encodeURIComponent(id)}`),

  /** Whole-document replace — the only write that rejects (422) an invalid document. */
  put: (id: string, document: AutomationDocument) =>
    api.put<DocumentWriteResult>(`/automations/${encodeURIComponent(id)}`, { document }),

  operations: (id: string, operations: Operation[]) =>
    api.post<DocumentWriteResult>(`/automations/${encodeURIComponent(id)}/operations`, { operations }),

  startRun: (id: string, trigger: Extract<RunTrigger, 'manual' | 'test'> = 'manual') =>
    api.post<{ runId: string }>(`/automations/${encodeURIComponent(id)}/runs`, { trigger }),

  listRuns: (id: string, limit?: number) =>
    api.get<RunSummary[]>(
      `/automations/${encodeURIComponent(id)}/runs${limit ? `?limit=${limit}` : ''}`
    ),

  getRun: (id: string, runId: string) =>
    api.get<RunDetail>(`/automations/${encodeURIComponent(id)}/runs/${encodeURIComponent(runId)}`),

  cancelRun: (id: string, runId: string) =>
    api.post<{ status: string }>(
      `/automations/${encodeURIComponent(id)}/runs/${encodeURIComponent(runId)}/cancel`
    ),

  /** Live progress for one run — GET-based SSE, combine with `parseSSE<RunEvent>`. */
  runEvents: (id: string, runId: string, signal?: AbortSignal) =>
    api.sseGet(
      `/automations/${encodeURIComponent(id)}/runs/${encodeURIComponent(runId)}/events`,
      signal
    ),
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
