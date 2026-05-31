/** @deprecated Re-export shim — import from `@/lib/api` instead. */
import { usage } from '@/lib/api';
import type { UsageEntry } from '@/lib/types';

export const listUsage = usage.list;
export const recordUsage = async (_e: Omit<UsageEntry, 'timestamp'>): Promise<void> => {
  // No-op — FastAPI persists usage inside /chat/stream and /automations/run.
};
