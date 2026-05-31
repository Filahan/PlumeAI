import 'server-only';

import { PROVIDER_BASE_URLS, type Provider, type InterviewMessage } from '@/lib/types';
import { resolveProviderKey } from '@/lib/agent/run';
import { listConfiguredTools, TOOLS } from '@/lib/tools/registry';

const BASE_PROMPT = `You are an automation designer. Interview the user about their intended automation so you can produce a precise, complete prompt for an autonomous agent that will then execute it.

The agent has three built-in tools:
- web_search(query): search the web
- web_fetch(url): GET and parse a web page
- http(method, url, headers?, body?): arbitrary HTTP method to APIs

{INTEGRATIONS}

Gather: (1) the data source / trigger, (2) what to do with the data, (3) the output destination, (4) any auth/credentials the agent will need, (5) schedule preference.

Rules:
- Ask ONE question at a time.
- Prefer 2-4 multiple-choice options when possible. Use open-ended only when needed.
- Respond ONLY as valid JSON. No prose, no code fences. Use one of:
  {"type":"ask","question":"<one sentence>","options":["A","B","C"]}
  (omit "options" for open-ended)
  OR
  {"type":"finalize","skill":"<complete prompt for the agent>"}
- The "skill" must be a clear instruction in plain English, with concrete URLs/parameters the user provided. Include any @<tool> mentions verbatim so the executor knows which integrations to use. Example:
  "Every morning, use @gmail to search 'after:today' (gmail_search), summarize the 5 most important threads, and POST a JSON body {\\"text\\": <summary>} to https://hooks.slack.com/services/XYZ."
- If the user @-mentions a tool that is NOT listed in "Available @-mention integrations" above, ask them to connect it in Settings first and do not finalize until they do.
- Stop early — 3 to 6 questions max. Don't over-interrogate.`;

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);  // YYYY-MM-DD
}

async function buildSystemPrompt(): Promise<string> {
  const configured = await listConfiguredTools();
  const configuredNames = new Set(configured.map((t) => t.name));
  let block: string;
  if (configured.length === 0) {
    const known = Object.values(TOOLS).map((t) => `- @${t.name} (NOT CONNECTED — tell the user to connect it in Settings before finalizing)`);
    block = `Available @-mention integrations: none connected yet.\nKnown but unconnected:\n${known.join('\n')}`;
  } else {
    const connected = configured.map((t) => `- @${t.name}: ${t.description}`);
    const unconnected = Object.values(TOOLS)
      .filter((t) => !configuredNames.has(t.name))
      .map((t) => `- @${t.name} (NOT CONNECTED)`);
    block = `Available @-mention integrations the user can reference:\n${connected.join('\n')}`;
    if (unconnected.length > 0) block += `\nKnown but not yet connected:\n${unconnected.join('\n')}`;
  }
  const dateLine = `Today's date is ${todayIso()}. When the user says "today", "yesterday", "last week", etc., write the CONCRETE date(s) into the finalized skill — never the literal words "today" or "yesterday". For Gmail searches, use the YYYY/MM/DD format (e.g. \`after:${todayIso().replace(/-/g, '/')}\`).`;
  return BASE_PROMPT.replace('{INTEGRATIONS}', block) + '\n\n' + dateLine;
}

export type InterviewResult =
  | { kind: 'ask'; question: string; options?: string[] }
  | { kind: 'finalize'; skill: string };

export async function interview(
  provider: Provider,
  model: string,
  history: InterviewMessage[],
  userMessage: string
): Promise<InterviewResult> {
  if (provider === 'anthropic') {
    throw new Error('Interview requires an OpenAI or OpenRouter model in this version.');
  }
  const apiKey = await resolveProviderKey(provider);
  const systemPrompt = await buildSystemPrompt();

  const messages: { role: 'system' | 'user' | 'assistant'; content: string }[] = [
    { role: 'system', content: systemPrompt },
    ...history.map((m) =>
      m.role === 'assistant'
        ? {
            role: 'assistant' as const,
            content: JSON.stringify({ type: 'ask', question: m.content, options: m.options ?? [] }),
          }
        : { role: 'user' as const, content: m.content }
    ),
    { role: 'user', content: userMessage },
  ];

  const res = await fetch(`${PROVIDER_BASE_URLS[provider]}/chat/completions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${apiKey}` },
    body: JSON.stringify({
      model,
      messages,
      response_format: { type: 'json_object' },
      temperature: 0.4,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err?.error?.message || `Interview LLM error: ${res.status}`);
  }
  const data = (await res.json()) as { choices?: Array<{ message?: { content?: string } }> };
  const content = data.choices?.[0]?.message?.content;
  if (typeof content !== 'string') throw new Error('Empty interview response.');

  let parsed: { type?: string; question?: unknown; options?: unknown; skill?: unknown };
  try {
    parsed = JSON.parse(content);
  } catch {
    // Model ignored response_format and returned prose — surface it as an open-ended
    // question so the conversation can continue instead of dead-ending on an opaque error.
    return { kind: 'ask', question: content.trim().slice(0, 500) };
  }

  if (parsed.type === 'ask' && typeof parsed.question === 'string') {
    const opts =
      Array.isArray(parsed.options) && parsed.options.length > 0
        ? (parsed.options.filter((o): o is string => typeof o === 'string'))
        : undefined;
    return { kind: 'ask', question: parsed.question, ...(opts ? { options: opts } : {}) };
  }
  if (parsed.type === 'finalize' && typeof parsed.skill === 'string' && parsed.skill.trim()) {
    return { kind: 'finalize', skill: parsed.skill.trim() };
  }
  throw new Error('Interviewer response did not match the expected shape.');
}
