import { NextRequest } from 'next/server';
import { requireSession } from '@/lib/auth';
import type { Provider } from '@/lib/types';
import type { AgentEvent } from '@/lib/agent/run';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const CHAT_SYSTEM_PROMPT =
  'You are a helpful assistant. You may use the provided tools when relevant — call them rather than ' +
  'saying you cannot. When you use a tool, briefly state what you did in plain language so the user ' +
  'sees what happened.';

interface ChatTurnInput {
  role: 'user' | 'assistant';
  content: string;
}

export async function POST(req: NextRequest) {
  try {
    await requireSession();
  } catch {
    return new Response('Unauthorized', { status: 401 });
  }

  const { ensureMigrations } = await import('@/lib/db');
  const { BUILTIN_TOOL_SCHEMAS } = await import('@/lib/agent/tools');
  const { streamAgent, resolveProviderKey } = await import('@/lib/agent/run');
  const { listConfiguredToolSchemas } = await import('@/lib/tools/registry');
  await ensureMigrations();

  const body = await req.json().catch(() => ({}));
  const provider = body?.provider as Provider | undefined;
  const model = typeof body?.model === 'string' ? body.model : '';
  const history = Array.isArray(body?.history) ? (body.history as ChatTurnInput[]) : [];
  const newMessage = typeof body?.newMessage === 'string' ? body.newMessage : '';

  if (!provider || !model || !newMessage) {
    return new Response('provider, model and newMessage are required', { status: 400 });
  }
  if (provider === 'anthropic') {
    return new Response('Anthropic is not supported on the tool-calling chat endpoint', { status: 400 });
  }

  let apiKey: string;
  try {
    apiKey = await resolveProviderKey(provider);
  } catch (e) {
    const msg = e instanceof Error ? e.message : 'Could not resolve API key';
    return Response.json({ error: msg }, { status: 400 });
  }

  const tools = [...BUILTIN_TOOL_SCHEMAS, ...(await listConfiguredToolSchemas())];
  const messages = [
    { role: 'system' as const, content: CHAT_SYSTEM_PROMPT },
    ...history
      .filter((m) => (m.role === 'user' || m.role === 'assistant') && typeof m.content === 'string')
      .map((m) => ({ role: m.role, content: m.content })),
    { role: 'user' as const, content: newMessage },
  ];

  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    async start(controller) {
      const send = (e: AgentEvent | { type: 'done'; status: string }) => {
        try {
          controller.enqueue(encoder.encode(`data: ${JSON.stringify(e)}\n\n`));
        } catch {
          // client disconnected; ignore
        }
      };
      const outcome = await streamAgent({
        provider,
        model,
        apiKey,
        messages,
        tools,
        signal: req.signal,
        emit: send,
      });
      send({ type: 'done', status: outcome.status });
      controller.close();
    },
  });

  return new Response(stream, {
    headers: {
      'Content-Type': 'text/event-stream; charset=utf-8',
      'Cache-Control': 'no-cache, no-transform',
      Connection: 'keep-alive',
    },
  });
}
