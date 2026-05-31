import { NextRequest } from 'next/server';
import { eq } from 'drizzle-orm';
import { tasks, usageEntries } from '@/lib/db/schema';
import { requireSession } from '@/lib/auth';
import type { Provider, TaskRun } from '@/lib/types';
import type { AgentEvent } from '@/lib/agent/run';

const MAX_RUNS_KEPT = 30;

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function POST(req: NextRequest) {
  try {
    await requireSession();
  } catch {
    return new Response('Unauthorized', { status: 401 });
  }

  // Lazy imports: `@/lib/db` throws if DATABASE_URL is unset, which must not happen
  // at build-time module evaluation — only at request time.
  const { db, ensureMigrations } = await import('@/lib/db');
  const { runAgent } = await import('@/lib/agent/run');
  await ensureMigrations();

  const body = await req.json().catch(() => ({}));
  const taskId = typeof body?.taskId === 'string' ? body.taskId : '';
  if (!taskId) return new Response('taskId required', { status: 400 });

  const [task] = await db.select().from(tasks).where(eq(tasks.id, taskId));
  if (!task) return new Response('Task not found', { status: 404 });

  const provider = task.provider as Provider;
  const model = task.model;
  const prompt = task.prompt;
  const encoder = new TextEncoder();

  const stream = new ReadableStream({
    async start(controller) {
      const send = (event: AgentEvent | { type: 'done'; status: string }) => {
        try {
          controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
        } catch {
          // client disconnected; ignore
        }
      };

      const startedAt = Date.now();
      await db
        .update(tasks)
        .set({ status: 'running', output: '', transcript: [], error: null, updatedAt: new Date() })
        .where(eq(tasks.id, taskId))
        .catch(() => {});

      const outcome = await runAgent({ provider, model, prompt, signal: req.signal, emit: send });

      // Append a TaskRun entry to history (capped at MAX_RUNS_KEPT).
      const endedAt = Date.now();
      const run: TaskRun = {
        status: outcome.status,
        startedAt,
        endedAt,
        durationMs: endedAt - startedAt,
        ...(outcome.error ? { error: outcome.error } : {}),
      };
      const nextRuns = [...((task.runs as TaskRun[] | null) ?? []), run].slice(-MAX_RUNS_KEPT);

      await db
        .update(tasks)
        .set({
          status: outcome.status,
          output: outcome.output,
          transcript: outcome.transcript,
          runs: nextRuns,
          error: outcome.error ?? null,
          updatedAt: new Date(),
        })
        .where(eq(tasks.id, taskId))
        .catch(() => {});

      if (outcome.usage.inputTokens || outcome.usage.outputTokens) {
        await db
          .insert(usageEntries)
          .values({
            id: crypto.randomUUID(),
            conversationId: null,
            provider,
            model,
            inputTokens: outcome.usage.inputTokens,
            outputTokens: outcome.usage.outputTokens,
            timestamp: new Date(),
          })
          .catch(() => {});
      }

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
