/** Typed wrappers for every FastAPI endpoint, grouped by domain.
 *
 *  Usage:
 *      import { settings, automations, usage } from '@/lib/api';
 *      const all = await automations.list();
 *
 *  SSE endpoints return a raw `Response` — combine with `parseSSE<Event>` from `./sse`.
 */

import { api } from './client';
import type { Settings, UsageEntry } from '@/lib/types';
import type {
  AssistantResponse,
  AutomationDetail,
  AutomationDocument,
  AutomationSummary,
  Catalog,
  DocumentWriteResult,
  McpServerInput,
  McpServerView,
  McpTestResult,
  Operation,
  RunDetail,
  RunSummary,
  RunWithAutomation,
  RunsPage,
  SchedulesResponse,
  SchedulesToggleResult,
  ValidateResult,
  VersionDetail,
  VersionSummary,
} from '@/lib/automations/types';

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

// ─── Tool catalog ───────────────────────────────────────────────────────────────────

export const tools = {
  /** Integrations (with live connection status), builtin actions and the tools of every
   *  registered MCP server. Single source of truth for the Tools page, the @-mention
   *  autocomplete, the step picker and the step inspector. */
  catalog: () => api.get<Catalog>('/tools'),
};

// ─── MCP servers ────────────────────────────────────────────────────────────────────

/** `{transport, config}` without a name — what `test` probes and what a `PUT` may carry. */
type McpConfigProbe = Pick<McpServerInput, 'transport' | 'config' | 'allowPrivateNetwork'>;

export const mcp = {
  /** Every registered server, with its cached tool listing and last sync outcome.
   *  Unwraps the `{servers}` envelope — nothing else in that response matters. */
  list: async (): Promise<McpServerView[]> =>
    (await api.get<{ servers: McpServerView[] }>('/mcp/servers')).servers ?? [],

  /** 201 even when the first connection attempt fails — the row exists either way and
   *  `lastError` says what went wrong, so nothing the user typed is lost. */
  create: (body: McpServerInput) => api.post<McpServerView>('/mcp/servers', body),

  /** Partial. `config` is REPLACED wholesale when present, so omit it entirely to keep
   *  the stored secrets, and send every value you want kept when you do send it. */
  update: (id: string, body: Partial<McpServerInput>) =>
    api.put<McpServerView>(`/mcp/servers/${encodeURIComponent(id)}`, body),

  setEnabled: (id: string, enabled: boolean) =>
    api.patch<McpServerView>(`/mcp/servers/${encodeURIComponent(id)}`, { enabled }),

  /** Re-read the server's tool list into the cached listing the catalog serves. */
  refresh: (id: string) =>
    api.post<McpServerView>(`/mcp/servers/${encodeURIComponent(id)}/refresh`),

  remove: (id: string): Promise<void> =>
    api.delete(`/mcp/servers/${encodeURIComponent(id)}`),

  /** Try a config without saving it: `{ok, tools}` or `{ok: false, error}`. */
  test: (body: McpConfigProbe) => api.post<McpTestResult>('/mcp/servers/test', body),
};

// ─── Automations ────────────────────────────────────────────────────────────────────

export const automations = {
  list: () => api.get<AutomationSummary[]>('/automations'),

  create: (body?: { name?: string; document?: AutomationDocument }) =>
    api.post<AutomationDetail>('/automations', body ?? {}),

  get: (id: string) => api.get<AutomationDetail>(`/automations/${encodeURIComponent(id)}`),

  /** Whole-document replace — the only write that rejects (422) an invalid document.
   *  The 422 body carries `extra.issues`; used by the JSON editor's explicit Save. */
  put: (id: string, document: AutomationDocument) =>
    api.put<DocumentWriteResult>(`/automations/${encodeURIComponent(id)}`, { document }),

  patch: (id: string, patch: { name?: string; enabled?: boolean }) =>
    api.patch<AutomationDetail>(`/automations/${encodeURIComponent(id)}`, patch),

  remove: (id: string): Promise<void> => api.delete(`/automations/${encodeURIComponent(id)}`),

  /** Dry run of the document validator — never writes. */
  validate: (document: AutomationDocument) =>
    api.post<ValidateResult>('/automations/validate', { document }),

  /** Incremental edits — one user gesture = one operation = one version. */
  operations: (id: string, operations: Operation[]) =>
    api.post<DocumentWriteResult>(`/automations/${encodeURIComponent(id)}/operations`, {
      operations,
    }),

  /** One assistant turn: describe an edit in plain language, get the new document back.
   *  Slow (an LLM round trip); 404 when no API key is configured for the automation's
   *  provider, 502 when the provider itself fails. */
  assistant: (id: string, message: string) =>
    api.post<AssistantResponse>(`/automations/${encodeURIComponent(id)}/assistant`, {
      message,
    }),

  /** Forgets the transcript. The document is untouched. */
  clearAssistant: (id: string): Promise<void> =>
    api.delete(`/automations/${encodeURIComponent(id)}/assistant`),

  versions: (id: string) =>
    api.get<VersionSummary[]>(`/automations/${encodeURIComponent(id)}/versions`),

  version: (id: string, number: number) =>
    api.get<VersionDetail>(`/automations/${encodeURIComponent(id)}/versions/${number}`),

  restore: (id: string, number: number) =>
    api.post<DocumentWriteResult>(
      `/automations/${encodeURIComponent(id)}/versions/${number}/restore`
    ),

  /** 202 + `{runId}`; 409 when a run is already active. */
  startRun: (id: string, trigger: 'manual' | 'test' = 'manual') =>
    api.post<{ runId: string }>(`/automations/${encodeURIComponent(id)}/runs`, { trigger }),

  listRuns: (id: string, opts?: { limit?: number; before?: number }) => {
    const qs = new URLSearchParams();
    if (opts?.limit !== undefined) qs.set('limit', String(opts.limit));
    if (opts?.before !== undefined) qs.set('before', String(opts.before));
    const suffix = qs.size > 0 ? `?${qs.toString()}` : '';
    return api.get<RunSummary[]>(`/automations/${encodeURIComponent(id)}/runs${suffix}`);
  },

  getRun: (id: string, runId: string) =>
    api.get<RunDetail>(`/automations/${encodeURIComponent(id)}/runs/${encodeURIComponent(runId)}`),

  cancelRun: (id: string, runId: string) =>
    api.post<{ status: string }>(
      `/automations/${encodeURIComponent(id)}/runs/${encodeURIComponent(runId)}/cancel`
    ),

  /** Live progress for one run — GET-based SSE, combine with `parseSSE<RunEvent>`
   *  (or just use `subscribeRun` from `@/lib/automations/run-stream`). */
  runEvents: (id: string, runId: string, signal?: AbortSignal) =>
    api.sseGet(
      `/automations/${encodeURIComponent(id)}/runs/${encodeURIComponent(runId)}/events`,
      signal
    ),
};

// ─── Activity (cross-automation runs + schedules) ───────────────────────────────────

/** Filters for the run feed. `before` is a cursor, not a window start: pass the previous
 *  page's `nextCursor` to walk backwards through history. */
export interface RunsQuery {
  limit?: number;
  before?: number;
  automationId?: string;
  status?: string;
}

function runsQuery(opts: RunsQuery | undefined): string {
  const qs = new URLSearchParams();
  if (opts?.limit !== undefined) qs.set('limit', String(opts.limit));
  if (opts?.before !== undefined) qs.set('before', String(opts.before));
  if (opts?.automationId) qs.set('automationId', opts.automationId);
  if (opts?.status) qs.set('status', opts.status);
  return qs.size > 0 ? `?${qs.toString()}` : '';
}

/** The Activity section: every automation's runs in one feed, and the schedule board.
 *
 *  Distinct from `automations.listRuns`, which is scoped to one automation and drives
 *  the editor's run panel — these are the cross-automation views. */
export const activity = {
  /** Newest first, across every automation. Each row carries its `automationName`. */
  runs: (opts?: RunsQuery) => api.get<RunsPage>(`/runs${runsQuery(opts)}`),

  /** One run by id alone — no automation id needed, and the response names it. */
  run: (runId: string) => api.get<RunWithAutomation>(`/runs/${encodeURIComponent(runId)}`),

  /** Every scheduled automation plus the account timezone times are shown in. */
  schedules: () => api.get<SchedulesResponse>('/schedules'),

  /** `null` means "every schedule" — that is what the Pause everything button sends. */
  pauseSchedules: (automationIds: string[] | null = null) =>
    api.post<SchedulesToggleResult>('/schedules/pause', { automationIds }),

  resumeSchedules: (automationIds: string[] | null = null) =>
    api.post<SchedulesToggleResult>('/schedules/resume', { automationIds }),
};

// ─── Usage ──────────────────────────────────────────────────────────────────────────

export const usage = {
  list: () => api.get<UsageEntry[]>('/usage'),
};
