export type Provider = 'openai' | 'anthropic';

export interface AttachmentRef {
  id: string;        // blob-store key (uuid)
  mime: string;      // 'image/jpeg' | 'image/png' | 'image/webp' | 'image/gif'
  width: number;
  height: number;
  size: number;      // bytes, post-resize
}

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
  attachments?: AttachmentRef[];
}

export interface Conversation {
  id: string;
  title: string;
  messages: Message[];
  createdAt: number;
  updatedAt: number;
  provider: Provider;
  model: string;
}

export interface ProviderConfig {
  id: string;
  provider: Provider;
  label: string;
  apiKey: string;
}

/** Client-facing tool connection info. Never includes secrets — tokens stay on the server. */
export interface ToolConnection {
  connected: boolean;
  /** Unix ms; omitted when unknown or not applicable. */
  expiresAt?: number;
  /** OAuth scopes granted. */
  scope?: string;
}

export interface Settings {
  providers: ProviderConfig[];
  defaultModel: { provider: Provider; model: string };
  /** Per-tool connection status (e.g. `tools.gmail.connected`). Tokens are NEVER exposed here. */
  tools: Record<string, ToolConnection>;
  /** App-level credential status per provider namespace (e.g. `toolCredentials.google = true`). */
  toolCredentials: Record<string, boolean>;
}

export function findApiKey(settings: Settings, provider: Provider): string {
  return settings.providers.find((p) => p.provider === provider)?.apiKey ?? '';
}

export function supportsVision(provider: Provider, model: string): boolean {
  if (provider === 'openai') return /^gpt-4o|^gpt-4\.1|^o\d/.test(model);
  if (provider === 'anthropic') return /^claude-3/.test(model);
  return false;
}

export interface UsageEntry {
  timestamp: number;
  conversationId: string;
  provider: Provider;
  model: string;
  inputTokens: number;
  outputTokens: number;
}

// ─── Automations (new /api/automations backend) ────────────────────────────────────

export type ValidationLevel = 'error' | 'warning';

export interface ValidationIssue {
  path: string;
  message: string;
  level: ValidationLevel;
}

export interface LastRunPayload {
  status: string;
  endedAt: number | null;
}

export interface AutomationSummary {
  id: string;
  name: string;
  enabled: boolean;
  triggerSummary: string;
  nextRunAt: number | null;
  lastRun: LastRunPayload | null;
  valid: boolean;
  updatedAt: number;
}

/** Loosely typed — the document language is owned by the backend (`app.schemas.documents`).
 *  Steps and settings are kept as `Record<string, unknown>` since this throwaway UI only
 *  needs to read/round-trip JSON, not model every step shape. */
export interface AutomationStep {
  id: string;
  name: string;
  type: 'action' | 'ai' | 'filter';
  settings: Record<string, unknown>;
  valid: boolean;
  retry?: { max_attempts: number; backoff_seconds: number } | null;
  timeout_seconds?: number | null;
  [key: string]: unknown;
}

export interface AutomationDocument {
  name: string;
  description?: string;
  model: { provider: Provider; model: string };
  trigger:
    | { type: 'manual' }
    | {
        type: 'schedule';
        settings:
          | { mode: 'cron'; cron: string; timezone?: string | null }
          | { mode: 'interval'; every_minutes: number; timezone?: string | null };
      };
  steps: AutomationStep[];
}

export interface AutomationDetail {
  id: string;
  name: string;
  enabled: boolean;
  document: AutomationDocument;
  versionNumber: number;
  issues: ValidationIssue[];
  nextRunAt: number | null;
  assistantMessages: Record<string, unknown>[];
  lastRun: LastRunPayload | null;
  createdAt: number;
  updatedAt: number;
}

/** Response shape shared by every document-writing endpoint (PUT, /operations, restore). */
export interface DocumentWriteResult {
  document: AutomationDocument;
  issues: ValidationIssue[];
  versionNumber: number;
  summary: string[];
}

/** Mutation ops accepted by `POST /automations/{id}/operations` — snake_case, matching
 *  the document language itself (see `app.schemas.documents.Operation`). */
export type Operation =
  | { op: 'add_step'; step: AutomationStep; index?: number }
  | { op: 'update_step'; step_id: string; patch: Record<string, unknown> }
  | { op: 'remove_step'; step_id: string }
  | { op: 'move_step'; step_id: string; index: number }
  | { op: 'set_trigger'; trigger: AutomationDocument['trigger'] }
  | { op: 'set_meta'; name?: string; description?: string; model?: { provider: Provider; model: string } };

export type RunTrigger = 'manual' | 'schedule' | 'test';
export type RunStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled';
export type RunStepStatus = 'pending' | 'running' | 'succeeded' | 'failed' | 'skipped' | 'cancelled';

export interface RunSummary {
  id: string;
  automationId: string;
  versionNumber: number | null;
  trigger: RunTrigger;
  status: RunStatus;
  stoppedByStepId: string | null;
  error: string | null;
  inputTokens: number;
  outputTokens: number;
  startedAt: number | null;
  endedAt: number | null;
  durationMs: number | null;
  createdAt: number;
}

export interface RunStep {
  id: string;
  stepId: string;
  index: number;
  name: string;
  type: string;
  status: RunStepStatus;
  attempt: number;
  resolvedInput: Record<string, unknown> | null;
  output: unknown;
  error: string | null;
  trace: Record<string, unknown>[];
  startedAt: number | null;
  endedAt: number | null;
  durationMs: number | null;
}

export interface RunDetail extends RunSummary {
  steps: RunStep[];
}

/** SSE events from `GET /automations/{id}/runs/{runId}/events`, discriminated on `type`.
 *  Kept loose (extra fields as `unknown`) — this UI only reads a handful of them. */
export type RunEvent =
  | { type: 'snapshot'; run: RunDetail }
  | { type: 'run_started'; [key: string]: unknown }
  | { type: 'step_started'; stepId: string; index: number; attempt: number }
  | { type: 'step_retry'; [key: string]: unknown }
  | { type: 'step_text'; stepId: string; delta: string }
  | { type: 'step_tool_call'; [key: string]: unknown }
  | { type: 'step_tool_result'; [key: string]: unknown }
  | { type: 'step_finished'; stepId: string; status: RunStepStatus; output?: unknown }
  | { type: 'run_finished'; status: RunStatus; error?: string | null };

export const PROVIDER_MODELS: Record<Provider, string[]> = {
  openai: ['gpt-4o', 'gpt-4o-mini', 'gpt-4.1', 'gpt-4.1-mini'],
  anthropic: ['claude-3-7-sonnet-20250219', 'claude-3-5-sonnet-20241022', 'claude-3-5-haiku-20241022'],
};

export const PROVIDER_NAMES: Record<Provider, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic',
};

export const PROVIDER_BASE_URLS: Record<Provider, string> = {
  openai: 'https://api.openai.com/v1',
  anthropic: 'https://api.anthropic.com/v1',
};

export const PROVIDER_ACCENT: Record<Provider, string> = {
  openai: 'text-[#10A37F]',
  anthropic: 'text-[#D97757]',
};
