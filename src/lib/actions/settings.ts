'use server';

import { eq } from 'drizzle-orm';
import { db, ensureMigrations } from '@/lib/db';
import { settings, type ProviderConfigEncrypted } from '@/lib/db/schema';
import { requireSession } from '@/lib/auth';
import { encrypt, decrypt } from '@/lib/crypto';
import type { Settings, ProviderConfig } from '@/lib/types';

async function init() {
  await requireSession();
  await ensureMigrations();
}

const DEFAULT_SETTINGS: Settings = {
  providers: [],
  defaultModel: { provider: 'openai', model: 'gpt-4o' },
  tools: {},
};

async function ensureRow(): Promise<void> {
  await db
    .insert(settings)
    .values({ id: 1, providers: [], defaultModel: DEFAULT_SETTINGS.defaultModel })
    .onConflictDoNothing();
}

export async function getSettings(): Promise<Settings> {
  await init();
  await ensureRow();
  const [row] = await db.select().from(settings).where(eq(settings.id, 1));
  if (!row) return DEFAULT_SETTINGS;
  const providers: ProviderConfig[] = await Promise.all(
    row.providers.map(async (p) => ({
      id: p.id,
      provider: p.provider,
      label: p.label,
      apiKey: p.apiKeyCiphertext ? await decrypt(p.apiKeyIv, p.apiKeyCiphertext) : '',
    }))
  );
  // Surface only `{connected}` for each tool — secrets stay encrypted server-side.
  const tools: Settings['tools'] = {};
  for (const [name, blob] of Object.entries(row.tools ?? {})) {
    tools[name] = { connected: !!(blob?.ciphertext && blob?.iv) };
  }
  return { providers, defaultModel: row.defaultModel, tools };
}

export async function disconnectTool(name: string): Promise<void> {
  await init();
  const [row] = await db.select().from(settings).where(eq(settings.id, 1));
  if (!row) return;
  const next = { ...row.tools };
  delete next[name];
  await db.update(settings).set({ tools: next }).where(eq(settings.id, 1));
}

export async function updateSettings(next: Settings): Promise<void> {
  await init();
  await ensureRow();
  const encryptedProviders: ProviderConfigEncrypted[] = await Promise.all(
    next.providers.map(async (p) => {
      if (!p.apiKey) {
        return {
          id: p.id,
          provider: p.provider,
          label: p.label,
          apiKeyCiphertext: '',
          apiKeyIv: '',
        };
      }
      const { iv, ct } = await encrypt(p.apiKey);
      return {
        id: p.id,
        provider: p.provider,
        label: p.label,
        apiKeyCiphertext: ct,
        apiKeyIv: iv,
      };
    })
  );
  await db
    .update(settings)
    .set({ providers: encryptedProviders, defaultModel: next.defaultModel })
    .where(eq(settings.id, 1));
}
