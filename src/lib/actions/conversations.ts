'use server';

import { and, desc, eq, inArray, sql } from 'drizzle-orm';
import { db, ensureMigrations } from '@/lib/db';
import { conversations, messages } from '@/lib/db/schema';
import { requireSession } from '@/lib/auth';
import type { Conversation, Message, Provider } from '@/lib/types';

async function init() {
  await requireSession();
  await ensureMigrations();
}

async function loadConversations(): Promise<Conversation[]> {
  const convs = await db.select().from(conversations).orderBy(desc(conversations.updatedAt));
  if (convs.length === 0) return [];
  const ids = convs.map((c) => c.id);
  const msgs = await db
    .select()
    .from(messages)
    .where(inArray(messages.conversationId, ids))
    .orderBy(messages.timestamp);
  const byConv = new Map<string, Message[]>();
  for (const m of msgs) {
    const arr = byConv.get(m.conversationId) ?? [];
    arr.push({
      id: m.id,
      role: m.role,
      content: m.content,
      timestamp: m.timestamp.getTime(),
      attachments: m.attachments ?? undefined,
    });
    byConv.set(m.conversationId, arr);
  }
  return convs.map((c) => ({
    id: c.id,
    title: c.title,
    provider: c.provider as Provider,
    model: c.model,
    createdAt: c.createdAt.getTime(),
    updatedAt: c.updatedAt.getTime(),
    messages: byConv.get(c.id) ?? [],
  }));
}

export async function listConversations(): Promise<Conversation[]> {
  await init();
  return loadConversations();
}

export async function createConversation(id: string, provider: Provider, model: string): Promise<void> {
  await init();
  const now = new Date();
  await db.insert(conversations).values({
    id,
    title: 'Nouvelle conversation',
    provider,
    model,
    createdAt: now,
    updatedAt: now,
  });
}

export async function addMessage(
  conversationId: string,
  message: Omit<Message, 'timestamp'>
): Promise<{ firstUserMessage: boolean }> {
  await init();
  const { id } = message;
  const now = new Date();

  // Determine if this is the first user message (drives title auto-rename).
  const existing = await db
    .select({ id: messages.id, role: messages.role })
    .from(messages)
    .where(eq(messages.conversationId, conversationId));
  const firstUserMessage =
    message.role === 'user' && existing.every((m) => m.role !== 'user');

  await db.insert(messages).values({
    id,
    conversationId,
    role: message.role,
    content: message.content,
    attachments: message.attachments ?? null,
    timestamp: now,
  });

  // Bump updatedAt; if first user message, also set the default title.
  const title = firstUserMessage
    ? message.content.slice(0, 40) + (message.content.length > 40 ? '...' : '')
    : undefined;
  await db
    .update(conversations)
    .set({ updatedAt: now, ...(title ? { title } : {}) })
    .where(eq(conversations.id, conversationId));

  return { firstUserMessage };
}

export async function updateMessage(
  conversationId: string,
  messageId: string,
  chunk: string,
  replace = false
): Promise<void> {
  await init();
  if (replace) {
    await db
      .update(messages)
      .set({ content: chunk })
      .where(and(eq(messages.id, messageId), eq(messages.conversationId, conversationId)));
  } else {
    await db
      .update(messages)
      .set({ content: sql`${messages.content} || ${chunk}` })
      .where(and(eq(messages.id, messageId), eq(messages.conversationId, conversationId)));
  }
  await db
    .update(conversations)
    .set({ updatedAt: new Date() })
    .where(eq(conversations.id, conversationId));
}

export async function renameConversation(id: string, title: string): Promise<void> {
  await init();
  if (!title) return;
  await db
    .update(conversations)
    .set({ title, updatedAt: new Date() })
    .where(eq(conversations.id, id));
}

export async function setConversationModel(
  id: string,
  provider: Provider,
  model: string
): Promise<void> {
  await init();
  await db
    .update(conversations)
    .set({ provider, model, updatedAt: new Date() })
    .where(eq(conversations.id, id));
}

export async function deleteConversation(id: string): Promise<void> {
  await init();
  await db.delete(conversations).where(eq(conversations.id, id));
}

