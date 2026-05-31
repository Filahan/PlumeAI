/** Thin client-side wrappers around the FastAPI automations endpoints. */

import { api } from '@/lib/api-client';
import type { Task, Provider, TaskSchedule, TaskStatus } from '@/lib/types';

export async function listTasks(): Promise<Task[]> {
  return api.get<Task[]>('/automations');
}

export async function createTask(
  id: string,
  prompt: string,
  schedule: TaskSchedule,
  provider: Provider,
  model: string
): Promise<void> {
  await api.post('/automations', { id, prompt, schedule, provider, model });
}

export async function updateTask(
  id: string,
  patch: {
    title?: string;
    prompt?: string;
    schedule?: TaskSchedule;
    status?: TaskStatus;
    output?: string;
    error?: string | null;
    provider?: Provider;
    model?: string;
  }
): Promise<void> {
  await api.patch(`/automations/${encodeURIComponent(id)}`, patch);
}

export async function deleteTask(id: string): Promise<void> {
  await api.delete(`/automations/${encodeURIComponent(id)}`);
}
