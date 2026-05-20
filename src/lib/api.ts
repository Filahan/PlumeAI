import { Provider, PROVIDER_BASE_URLS } from './types';

export type TextPart = { type: 'text'; text: string };
export type ImagePart = { type: 'image'; mime: string; base64: string };
export type ChatContent = string | Array<TextPart | ImagePart>;
export type ChatMessage = { role: 'user' | 'assistant'; content: ChatContent };

function mapPartsForOpenAI(content: ChatContent) {
  if (typeof content === 'string') return content;
  return content.map((p) =>
    p.type === 'text'
      ? { type: 'text', text: p.text }
      : { type: 'image_url', image_url: { url: `data:${p.mime};base64,${p.base64}`, detail: 'auto' } }
  );
}

function mapPartsForAnthropic(content: ChatContent) {
  if (typeof content === 'string') return content;
  return content.map((p) =>
    p.type === 'text'
      ? { type: 'text', text: p.text }
      : { type: 'image', source: { type: 'base64', media_type: p.mime, data: p.base64 } }
  );
}

function hasImages(messages: ChatMessage[]): boolean {
  return messages.some((m) => Array.isArray(m.content) && m.content.some((p) => p.type === 'image'));
}

const STREAM_TIMEOUT_MS = 5 * 60 * 1000;
const MAX_BUFFER_BYTES = 1_000_000;

// Anthropic Messages API is stable on this version since 2023-06-01.
// Bumping requires re-validating response shape (system param, content blocks).
const ANTHROPIC_VERSION = '2023-06-01';

export type Usage = { inputTokens: number; outputTokens: number };

export async function streamChat(
  provider: Provider,
  model: string,
  apiKey: string,
  messages: ChatMessage[],
  onChunk: (chunk: string) => void,
  onUsage?: (usage: Usage) => void
): Promise<{ controller: AbortController; done: Promise<void> }> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(new Error('Stream timeout')), STREAM_TIMEOUT_MS);

  const donePromise = (async () => {
    try {
      if (provider === 'anthropic') {
        await streamAnthropic(model, apiKey, messages, onChunk, controller.signal, onUsage);
      } else {
        await streamOpenAICompatible(provider, model, apiKey, messages, onChunk, controller.signal, onUsage);
      }
    } finally {
      clearTimeout(timeoutId);
    }
  })();

  return { controller, done: donePromise };
}

async function streamAnthropic(
  model: string,
  apiKey: string,
  messages: ChatMessage[],
  onChunk: (chunk: string) => void,
  signal: AbortSignal,
  onUsage?: (usage: Usage) => void
) {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'x-api-key': apiKey,
    'anthropic-version': ANTHROPIC_VERSION,
  };
  // Image attachments require the browser-access header.
  if (hasImages(messages)) headers['anthropic-dangerous-direct-browser-access'] = 'true';

  const res = await fetch(`${PROVIDER_BASE_URLS.anthropic}/messages`, {
    method: 'POST',
    headers,
    body: JSON.stringify({
      model,
      max_tokens: 4096,
      messages: messages.map((m) => ({ role: m.role, content: mapPartsForAnthropic(m.content) })),
      stream: true,
    }),
    signal,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error?.message || `Anthropic API error: ${res.status}`);
  }

  let inputTokens = 0;
  let outputTokens = 0;
  await consumeSSE(res, (parsed) => {
    if (parsed.type === 'content_block_delta' && parsed.delta?.type === 'text_delta' && parsed.delta.text) {
      onChunk(parsed.delta.text);
    }
    // Anthropic emits usage on message_start (input) and the final message_delta (output)
    const usage = (parsed as { message?: { usage?: { input_tokens?: number; output_tokens?: number } }; usage?: { input_tokens?: number; output_tokens?: number } });
    if (usage.message?.usage?.input_tokens) inputTokens = usage.message.usage.input_tokens;
    if (usage.usage?.input_tokens) inputTokens = usage.usage.input_tokens;
    if (usage.usage?.output_tokens) outputTokens = usage.usage.output_tokens;
  });
  if (onUsage && (inputTokens || outputTokens)) onUsage({ inputTokens, outputTokens });
}

async function streamOpenAICompatible(
  provider: Provider,
  model: string,
  apiKey: string,
  messages: ChatMessage[],
  onChunk: (chunk: string) => void,
  signal: AbortSignal,
  onUsage?: (usage: Usage) => void
) {
  const res = await fetch(`${PROVIDER_BASE_URLS[provider]}/chat/completions`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify({
      model,
      messages: messages.map((m) => ({ role: m.role, content: mapPartsForOpenAI(m.content) })),
      stream: true,
      stream_options: { include_usage: true },
    }),
    signal,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error?.message || `API error: ${res.status}`);
  }

  let inputTokens = 0;
  let outputTokens = 0;
  await consumeSSE(res, (parsed) => {
    const content = parsed.choices?.[0]?.delta?.content;
    if (content) onChunk(content);
    const usage = (parsed as { usage?: { prompt_tokens?: number; completion_tokens?: number } }).usage;
    if (usage?.prompt_tokens) inputTokens = usage.prompt_tokens;
    if (usage?.completion_tokens) outputTokens = usage.completion_tokens;
  });
  if (onUsage && (inputTokens || outputTokens)) onUsage({ inputTokens, outputTokens });
}

// SSE payload shapes vary by provider; callers narrow with optional chaining.
type SSEEvent = Record<string, unknown> & {
  type?: string;
  delta?: { type?: string; text?: string };
  choices?: Array<{ delta?: { content?: string } }>;
};

export async function generateTitle(
  provider: Provider,
  model: string,
  apiKey: string,
  userMessage: string,
  assistantMessage: string
): Promise<string> {
  const systemPrompt =
    'You generate a concise 3-5 word title for a chat conversation. ' +
    "Reply with ONLY the title text — no quotes, no punctuation, no prefix, in the user's language.";
  const userPrompt = `USER: ${userMessage}\n\nASSISTANT: ${assistantMessage}`;

  if (provider === 'anthropic') {
    const res = await fetch(`${PROVIDER_BASE_URLS.anthropic}/messages`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-api-key': apiKey,
        'anthropic-version': ANTHROPIC_VERSION,
      },
      body: JSON.stringify({
        model,
        max_tokens: 40,
        system: systemPrompt,
        messages: [{ role: 'user', content: userPrompt }],
      }),
    });
    if (!res.ok) throw new Error(`Title API error: ${res.status}`);
    const data = await res.json();
    return (data.content?.[0]?.text ?? '').trim();
  }

  const res = await fetch(`${PROVIDER_BASE_URLS[provider]}/chat/completions`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify({
      model,
      max_tokens: 40,
      messages: [
        { role: 'system', content: systemPrompt },
        { role: 'user', content: userPrompt },
      ],
    }),
  });
  if (!res.ok) throw new Error(`Title API error: ${res.status}`);
  const data = await res.json();
  return (data.choices?.[0]?.message?.content ?? '').trim();
}

async function consumeSSE(res: Response, onEvent: (parsed: SSEEvent) => void) {
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    if (buffer.length > MAX_BUFFER_BYTES) {
      reader.cancel();
      throw new Error('Stream buffer overflow');
    }
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      const data = line.slice(6);
      if (data === '[DONE]') continue;
      try {
        onEvent(JSON.parse(data));
      } catch {
        // malformed event line — skip and keep going
      }
    }
  }
}
