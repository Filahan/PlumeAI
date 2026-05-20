'use server';

import { gte, asc } from 'drizzle-orm';
import { db, ensureMigrations } from '@/lib/db';
import { usageEntries } from '@/lib/db/schema';
import { requireSession } from '@/lib/auth';
import type { Provider, UsageEntry } from '@/lib/types';

async function init() {
  await requireSession();
  await ensureMigrations();
}

export async function listUsage(lookbackMs?: number): Promise<UsageEntry[]> {
  await init();
  const rows = lookbackMs && Number.isFinite(lookbackMs)
    ? await db
        .select()
        .from(usageEntries)
        .where(gte(usageEntries.timestamp, new Date(Date.now() - lookbackMs)))
        .orderBy(asc(usageEntries.timestamp))
    : await db.select().from(usageEntries).orderBy(asc(usageEntries.timestamp));
  return rows.map((r) => ({
    timestamp: r.timestamp.getTime(),
    conversationId: r.conversationId ?? '',
    provider: r.provider as Provider,
    model: r.model,
    inputTokens: r.inputTokens,
    outputTokens: r.outputTokens,
  }));
}

export async function recordUsage(entry: Omit<UsageEntry, 'timestamp'>): Promise<void> {
  await init();
  await db.insert(usageEntries).values({
    id: crypto.randomUUID(),
    conversationId: entry.conversationId || null,
    provider: entry.provider,
    model: entry.model,
    inputTokens: entry.inputTokens,
    outputTokens: entry.outputTokens,
    timestamp: new Date(),
  });
}

