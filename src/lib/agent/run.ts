import 'server-only';

import { eq } from 'drizzle-orm';
import { db } from '@/lib/db';
import { settings } from '@/lib/db/schema';
import { decrypt } from '@/lib/crypto';
import { PROVIDER_BASE_URLS, type Provider, type TranscriptStep } from '@/lib/types';
import { BUILTIN_TOOL_SCHEMAS, executeTool, redactArgs } from '@/lib/agent/tools';
import { listConfiguredToolSchemas } from '@/lib/tools/registry';

const MAX_ITERATIONS = 8;

function buildSystemPrompt(): string {
  const today = new Date().toISOString().slice(0, 10);  // YYYY-MM-DD
  return (
    `Today's date is ${today}. When the task mentions "today", "yesterday", "last week", etc., resolve them to concrete dates yourself before calling tools. For Gmail searches specifically, the date format Gmail expects is YYYY/MM/DD (e.g. \`after:${today.replace(/-/g, '/')}\`) — never pass the literal word "today" to the Gmail API.\n\n` +
    'You are an automation agent. Use the available tools to actually accomplish the task — ' +
    'search the web, read pages, call HTTP APIs (GET/POST/PUT/PATCH/DELETE), or use any connected ' +
    'integration tools (e.g. Gmail) — rather than saying you cannot. ' +
    'When the task is complete, reply with only the final result.'
  );
}

export type AgentEvent =
  | { type: 'text'; delta: string }
  | { type: 'tool_call'; id: string; tool: string; args: string }
  | { type: 'tool_result'; id: string; tool: string; ok: boolean; result: string }
  | { type: 'final'; text: string }
  | { type: 'error'; message: string };

export interface AgentOutcome {
  status: 'succeeded' | 'failed' | 'cancelled';
  output: string;
  transcript: TranscriptStep[];
  error?: string;
  usage: { inputTokens: number; outputTokens: number };
}

type ToolCallAcc = { id: string; name: string; args: string };
export type ChatMsg =
  | { role: 'system' | 'user'; content: string }
  | { role: 'assistant'; content: string | null; tool_calls?: { id: string; type: 'function'; function: { name: string; arguments: string } }[] }
  | { role: 'tool'; tool_call_id: string; content: string };
export type ToolSchema = { type: 'function'; function: { name: string; description: string; parameters: unknown } };

export async function resolveProviderKey(provider: Provider): Promise<string> {
  const [row] = await db.select().from(settings).where(eq(settings.id, 1));
  const cfg = row?.providers.find((p) => p.provider === provider);
  if (!cfg?.apiKeyCiphertext) throw new Error(`No API key configured for ${provider}.`);
  return decrypt(cfg.apiKeyIv, cfg.apiKeyCiphertext);
}

interface RoundResult {
  assistantText: string;
  toolCalls: ToolCallAcc[];
  usage: { inputTokens: number; outputTokens: number };
}

async function streamRound(
  baseUrl: string,
  model: string,
  apiKey: string,
  messages: ChatMsg[],
  tools: ToolSchema[],
  signal: AbortSignal,
  onText: (delta: string) => void
): Promise<RoundResult> {
  const res = await fetch(`${baseUrl}/chat/completions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${apiKey}` },
    body: JSON.stringify({ model, messages, tools, stream: true, stream_options: { include_usage: true } }),
    signal,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err?.error?.message || `LLM API error: ${res.status}`);
  }

  let assistantText = '';
  const toolAcc: Record<number, ToolCallAcc> = {};
  const usage = { inputTokens: 0, outputTokens: 0 };
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      const data = line.slice(6);
      if (data === '[DONE]') continue;
      let parsed: {
        choices?: Array<{ delta?: { content?: string; tool_calls?: Array<{ index: number; id?: string; function?: { name?: string; arguments?: string } }> } }>;
        usage?: { prompt_tokens?: number; completion_tokens?: number };
      };
      try {
        parsed = JSON.parse(data);
      } catch {
        continue;
      }
      const delta = parsed.choices?.[0]?.delta;
      if (delta?.content) {
        assistantText += delta.content;
        onText(delta.content);
      }
      for (const tc of delta?.tool_calls ?? []) {
        const acc = (toolAcc[tc.index] ??= { id: '', name: '', args: '' });
        if (tc.id) acc.id = tc.id;
        if (tc.function?.name) acc.name = tc.function.name;
        if (tc.function?.arguments) acc.args += tc.function.arguments;
      }
      if (parsed.usage?.prompt_tokens) usage.inputTokens = parsed.usage.prompt_tokens;
      if (parsed.usage?.completion_tokens) usage.outputTokens = parsed.usage.completion_tokens;
    }
  }
  return { assistantText, toolCalls: Object.values(toolAcc).filter((t) => t.name), usage };
}

/** Core tool-using agent loop. Caller provides the full history (system + user/assistant turns)
 *  and the tool schemas. Reusable across automations and the conversational chat. */
export async function streamAgent(opts: {
  provider: Provider;
  model: string;
  apiKey: string;
  messages: ChatMsg[];   // mutated as the loop progresses (assistant + tool messages appended)
  tools: ToolSchema[];
  signal: AbortSignal;
  emit: (e: AgentEvent) => void;
}): Promise<AgentOutcome> {
  const { provider, model, apiKey, messages, tools, signal, emit } = opts;
  const transcript: TranscriptStep[] = [];
  const usage = { inputTokens: 0, outputTokens: 0 };
  const baseUrl = PROVIDER_BASE_URLS[provider];

  try {
    for (let iter = 0; iter < MAX_ITERATIONS; iter++) {
      const round = await streamRound(baseUrl, model, apiKey, messages, tools, signal, (delta) =>
        emit({ type: 'text', delta })
      );
      usage.inputTokens += round.usage.inputTokens;
      usage.outputTokens += round.usage.outputTokens;

      if (round.assistantText) transcript.push({ kind: 'assistant', text: round.assistantText });

      if (round.toolCalls.length === 0) {
        emit({ type: 'final', text: round.assistantText });
        return { status: 'succeeded', output: round.assistantText, transcript, usage };
      }

      messages.push({
        role: 'assistant',
        content: round.assistantText || null,
        tool_calls: round.toolCalls.map((t) => ({ id: t.id, type: 'function', function: { name: t.name, arguments: t.args } })),
      });

      // Execute (parallel), but record transcript + tool messages in call order.
      const results = await Promise.all(
        round.toolCalls.map(async (tc) => {
          emit({ type: 'tool_call', id: tc.id, tool: tc.name, args: redactArgs(tc.args) });
          const result = await executeTool(tc.name, tc.args, signal);
          emit({ type: 'tool_result', id: tc.id, tool: tc.name, ok: result.ok, result: result.content });
          return { tc, result };
        })
      );
      for (const { tc, result } of results) {
        transcript.push({ kind: 'tool', tool: tc.name, args: redactArgs(tc.args), result: result.content, ok: result.ok });
        messages.push({ role: 'tool', tool_call_id: tc.id, content: result.content });
      }
    }

    const message = `Stopped after ${MAX_ITERATIONS} tool rounds without a final answer.`;
    emit({ type: 'error', message });
    return { status: 'failed', output: '', transcript, error: message, usage };
  } catch (e) {
    if (signal.aborted) return { status: 'cancelled', output: '', transcript, usage };
    const message = e instanceof Error ? e.message : 'Run failed.';
    emit({ type: 'error', message });
    return { status: 'failed', output: '', transcript, error: message, usage };
  }
}

export async function runAgent(
  opts: { provider: Provider; model: string; prompt: string; signal: AbortSignal; emit: (e: AgentEvent) => void }
): Promise<AgentOutcome> {
  const { provider, model, prompt, signal, emit } = opts;
  const transcript: TranscriptStep[] = [];
  const usage = { inputTokens: 0, outputTokens: 0 };

  if (provider === 'anthropic') {
    const message = 'Tool-using tasks require an OpenAI or OpenRouter model in this version.';
    emit({ type: 'error', message });
    return { status: 'failed', output: '', transcript, error: message, usage };
  }

  let apiKey: string;
  try {
    apiKey = await resolveProviderKey(provider);
  } catch (e) {
    const message = e instanceof Error ? e.message : 'Could not resolve API key.';
    emit({ type: 'error', message });
    return { status: 'failed', output: '', transcript, error: message, usage };
  }

  const tools: ToolSchema[] = [...BUILTIN_TOOL_SCHEMAS, ...(await listConfiguredToolSchemas())];
  const messages: ChatMsg[] = [
    { role: 'system', content: buildSystemPrompt() },
    { role: 'user', content: prompt },
  ];

  return streamAgent({ provider, model, apiKey, messages, tools, signal, emit });
}
