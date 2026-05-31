/** Thin client-side wrappers around the FastAPI usage endpoint.
 *
 *  `recordUsage` is now a no-op client-side: FastAPI persists every LLM round automatically
 *  inside its /chat/stream and /automations/run routes. We keep the function exported for
 *  backward compatibility with the chat-view's `onRecordUsage` callback prop.
 */

import { api } from '@/lib/api-client';
import type { UsageEntry } from '@/lib/types';

export async function listUsage(): Promise<UsageEntry[]> {
  return api.get<UsageEntry[]>('/usage');
}

export async function recordUsage(_entry: Omit<UsageEntry, 'timestamp'>): Promise<void> {
  // No-op — usage is recorded server-side as part of the agent SSE finalization.
}
