export type Provider = 'openai' | 'anthropic' | 'openrouter';

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
}

export function findApiKey(settings: Settings, provider: Provider): string {
  return settings.providers.find((p) => p.provider === provider)?.apiKey ?? '';
}

export function supportsVision(provider: Provider, model: string): boolean {
  if (provider === 'openai') return /^gpt-4o|^gpt-4\.1|^o\d/.test(model);
  if (provider === 'anthropic') return /^claude-3/.test(model);
  if (provider === 'openrouter') {
    return /^openai\/gpt-4o|^anthropic\/claude-3|^google\/gemini/.test(model);
  }
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

export type TaskStatus = 'idle' | 'running' | 'succeeded' | 'failed' | 'cancelled';

export type TaskSchedule = 'manual' | 'hourly' | 'daily' | 'weekly';

export const TASK_SCHEDULE_LABELS: Record<TaskSchedule, string> = {
  manual: 'Manual',
  hourly: 'Every hour',
  daily: 'Every day',
  weekly: 'Every week',
};

export interface AssistantStep {
  kind: 'assistant';
  text: string;
}
export interface ToolStep {
  kind: 'tool';
  tool: string;   // e.g. 'web_fetch'
  args: string;   // JSON string of arguments, secrets redacted
  result: string; // truncated tool result text
  ok: boolean;
}
export type TranscriptStep = AssistantStep | ToolStep;

export interface InterviewMessage {
  role: 'user' | 'assistant';
  content: string;       // displayed text (question or user reply)
  options?: string[];    // present when the assistant proposes choices
}

/** One completed execution of a task. Appended to `Task.runs` (capped at 30) at the end of
 *  each Run, providing the Airflow-style strip in `ExecutionsOverview`. */
export interface TaskRun {
  status: 'succeeded' | 'failed' | 'cancelled';
  startedAt: number;       // unix ms
  endedAt: number;         // unix ms
  durationMs: number;
  error?: string;
}

export interface Task {
  id: string;
  /** LLM-generated 3-5 word title from the first interview exchange. Falls back to a slice of
   *  the prompt when missing. Mirrors how chat conversations get auto-titled. */
  title?: string;
  prompt: string;        // the compiled "skill" — empty while the interview is in progress
  messages: InterviewMessage[];
  schedule: TaskSchedule;
  status: TaskStatus;
  output?: string;
  transcript: TranscriptStep[];
  /** History of past executions (most recent last, capped at 30). */
  runs: TaskRun[];
  provider: Provider;
  model: string;
  error?: string;
  createdAt: number;
  updatedAt: number;
}

export const PROVIDER_MODELS: Record<Provider, string[]> = {
  openai: ['gpt-4o', 'gpt-4o-mini', 'gpt-4.1', 'gpt-4.1-mini'],
  anthropic: ['claude-3-7-sonnet-20250219', 'claude-3-5-sonnet-20241022', 'claude-3-5-haiku-20241022'],
  openrouter: ['openai/gpt-4o', 'anthropic/claude-3.7-sonnet', 'google/gemini-2.5-pro-preview-03-25', 'meta-llama/llama-4-maverick'],
};

export const PROVIDER_NAMES: Record<Provider, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  openrouter: 'OpenRouter',
};

export const PROVIDER_BASE_URLS: Record<Provider, string> = {
  openai: 'https://api.openai.com/v1',
  anthropic: 'https://api.anthropic.com/v1',
  openrouter: 'https://openrouter.ai/api/v1',
};

export const PROVIDER_ACCENT: Record<Provider, string> = {
  openai: 'text-[#10A37F]',
  anthropic: 'text-[#D97706]',
  openrouter: 'text-[#6366f1]',
};
