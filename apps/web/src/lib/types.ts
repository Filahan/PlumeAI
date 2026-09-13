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
