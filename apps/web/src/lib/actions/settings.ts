/** Thin client-side wrappers around the FastAPI settings endpoints. */

import { api } from '@/lib/api-client';
import type { Settings } from '@/lib/types';

export async function getSettings(): Promise<Settings> {
  return api.get<Settings>('/settings');
}

export async function updateSettings(next: Settings): Promise<void> {
  await api.put<Settings>('/settings', next);
}

export async function disconnectTool(name: string): Promise<void> {
  await api.post(`/tools/${encodeURIComponent(name)}/disconnect`);
}
