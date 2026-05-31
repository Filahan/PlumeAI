'use server';

import { desc, eq } from 'drizzle-orm';
import { db, ensureMigrations } from '@/lib/db';
import { tasks } from '@/lib/db/schema';
import { requireSession } from '@/lib/auth';
import type { Task, Provider, TaskSchedule, TaskStatus } from '@/lib/types';

async function init() {
  await requireSession();
  await ensureMigrations();
}

export async function listTasks(): Promise<Task[]> {
  await init();
  const rows = await db.select().from(tasks).orderBy(desc(tasks.createdAt));
  return rows.map((r) => ({
    id: r.id,
    prompt: r.prompt,
    messages: r.messages ?? [],
    schedule: r.schedule,
    status: r.status,
    output: r.output ?? undefined,
    transcript: r.transcript ?? [],
    provider: r.provider as Provider,
    model: r.model,
    error: r.error ?? undefined,
    createdAt: r.createdAt.getTime(),
    updatedAt: r.updatedAt.getTime(),
  }));
}

export async function createTask(
  id: string,
  prompt: string,
  schedule: TaskSchedule,
  provider: Provider,
  model: string
): Promise<void> {
  await init();
  const now = new Date();
  await db.insert(tasks).values({
    id,
    prompt,
    messages: [],
    schedule,
    status: 'idle',
    provider,
    model,
    createdAt: now,
    updatedAt: now,
  });
}

export async function updateTask(
  id: string,
  patch: {
    prompt?: string;
    schedule?: TaskSchedule;
    status?: TaskStatus;
    output?: string;
    error?: string | null;
    provider?: Provider;
    model?: string;
  }
): Promise<void> {
  await init();
  await db
    .update(tasks)
    .set({
      ...(patch.prompt !== undefined ? { prompt: patch.prompt } : {}),
      ...(patch.schedule !== undefined ? { schedule: patch.schedule } : {}),
      ...(patch.status !== undefined ? { status: patch.status } : {}),
      ...(patch.output !== undefined ? { output: patch.output } : {}),
      ...(patch.error !== undefined ? { error: patch.error } : {}),
      ...(patch.provider !== undefined ? { provider: patch.provider } : {}),
      ...(patch.model !== undefined ? { model: patch.model } : {}),
      updatedAt: new Date(),
    })
    .where(eq(tasks.id, id));
}

export async function deleteTask(id: string): Promise<void> {
  await init();
  await db.delete(tasks).where(eq(tasks.id, id));
}
