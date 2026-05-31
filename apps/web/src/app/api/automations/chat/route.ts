import { NextRequest } from 'next/server';
import { eq } from 'drizzle-orm';
import { tasks } from '@/lib/db/schema';
import { requireSession } from '@/lib/auth';
import type { Provider, InterviewMessage } from '@/lib/types';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function POST(req: NextRequest) {
  try {
    await requireSession();
  } catch {
    return new Response('Unauthorized', { status: 401 });
  }

  const { db, ensureMigrations } = await import('@/lib/db');
  const { interview } = await import('@/lib/agent/interview');
  const { generateTaskTitle } = await import('@/lib/agent/generate-title');
  await ensureMigrations();

  const body = await req.json().catch(() => ({}));
  const taskId = typeof body?.taskId === 'string' ? body.taskId : '';
  const message = typeof body?.message === 'string' ? body.message.trim() : '';
  if (!taskId || !message) return new Response('taskId + message required', { status: 400 });

  const [task] = await db.select().from(tasks).where(eq(tasks.id, taskId));
  if (!task) return new Response('Task not found', { status: 404 });

  const history: InterviewMessage[] = task.messages ?? [];
  const isFirstExchange = history.length === 0;

  // Run interview + title generation in parallel — no latency cost on first exchange.
  const interviewPromise = interview(task.provider as Provider, task.model, history, message);
  const titlePromise: Promise<string> = isFirstExchange && !task.title
    ? generateTaskTitle(task.provider as Provider, task.model, message)
    : Promise.resolve(task.title ?? '');

  let result;
  try {
    result = await interviewPromise;
  } catch (e) {
    const errMsg = e instanceof Error ? e.message : 'Interview failed.';
    return Response.json({ error: errMsg }, { status: 502 });
  }
  const generatedTitle = await titlePromise;

  const userMsg: InterviewMessage = { role: 'user', content: message };
  const assistantMsg: InterviewMessage =
    result.kind === 'ask'
      ? { role: 'assistant', content: result.question, ...(result.options ? { options: result.options } : {}) }
      : { role: 'assistant', content: 'Skill ready.' };
  const nextMessages = [...history, userMsg, assistantMsg];

  await db
    .update(tasks)
    .set({
      messages: nextMessages,
      ...(generatedTitle && !task.title ? { title: generatedTitle } : {}),
      ...(result.kind === 'finalize' ? { prompt: result.skill } : {}),
      updatedAt: new Date(),
    })
    .where(eq(tasks.id, taskId));

  return Response.json({
    ...(result.kind === 'ask'
      ? { question: result.question, options: result.options }
      : { finalized: true, skill: result.skill }),
    ...(generatedTitle && !task.title ? { title: generatedTitle } : {}),
  });
}
