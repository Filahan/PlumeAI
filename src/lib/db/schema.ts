import { pgTable, text, integer, jsonb, timestamp, index } from 'drizzle-orm/pg-core';
import type { AttachmentRef, ProviderConfig, Provider, TaskStatus, TaskSchedule, TranscriptStep, InterviewMessage, TaskRun } from '@/lib/types';

// Stored ProviderConfig with the apiKey replaced by ciphertext + iv. Plaintext apiKey
// never touches the DB.
export type ProviderConfigEncrypted = Omit<ProviderConfig, 'apiKey'> & {
  apiKeyCiphertext: string;
  apiKeyIv: string;
};

export const conversations = pgTable('conversations', {
  id: text('id').primaryKey(),
  title: text('title').notNull(),
  provider: text('provider').notNull(),
  model: text('model').notNull(),
  createdAt: timestamp('created_at', { withTimezone: true }).notNull().defaultNow(),
  updatedAt: timestamp('updated_at', { withTimezone: true }).notNull().defaultNow(),
});

export const messages = pgTable(
  'messages',
  {
    id: text('id').primaryKey(),
    conversationId: text('conversation_id')
      .notNull()
      .references(() => conversations.id, { onDelete: 'cascade' }),
    role: text('role').$type<'user' | 'assistant'>().notNull(),
    content: text('content').notNull(),
    attachments: jsonb('attachments').$type<AttachmentRef[]>(),
    timestamp: timestamp('timestamp', { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    conversationIdx: index('messages_conversation_idx').on(table.conversationId),
    timestampIdx: index('messages_timestamp_idx').on(table.timestamp),
  })
);

/** Encrypted blob (one per tool name) stored inside `settings.tools`. Decrypts to a tool-specific
 *  JSON payload (e.g. for Gmail: access_token, refresh_token, expires_at, scope). */
export type ToolCredsEncrypted = { ciphertext: string; iv: string };

export const settings = pgTable('settings', {
  // Single-row table; we keep id=1 as a sentinel for the single-user mode.
  id: integer('id').primaryKey().default(1),
  providers: jsonb('providers').$type<ProviderConfigEncrypted[]>().notNull().default([]),
  defaultModel: jsonb('default_model')
    .$type<{ provider: Provider; model: string }>()
    .notNull(),
  tools: jsonb('tools').$type<Record<string, ToolCredsEncrypted>>().notNull().default({}),
});

export const tasks = pgTable(
  'tasks',
  {
    id: text('id').primaryKey(),
    ownerId: text('owner_id'),
    title: text('title'),
    prompt: text('prompt').notNull(),
    messages: jsonb('messages').$type<InterviewMessage[]>().notNull().default([]),
    schedule: text('schedule').$type<TaskSchedule>().notNull().default('manual'),
    status: text('status').$type<TaskStatus>().notNull().default('idle'),
    output: text('output'),
    transcript: jsonb('transcript').$type<TranscriptStep[]>().notNull().default([]),
    runs: jsonb('runs').$type<TaskRun[]>().notNull().default([]),
    provider: text('provider').notNull(),
    model: text('model').notNull(),
    error: text('error'),
    createdAt: timestamp('created_at', { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp('updated_at', { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    createdIdx: index('tasks_created_idx').on(table.createdAt),
  })
);

export const usageEntries = pgTable(
  'usage_entries',
  {
    id: text('id').primaryKey(),
    conversationId: text('conversation_id'),
    provider: text('provider').notNull(),
    model: text('model').notNull(),
    inputTokens: integer('input_tokens').notNull(),
    outputTokens: integer('output_tokens').notNull(),
    timestamp: timestamp('timestamp', { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    timestampIdx: index('usage_timestamp_idx').on(table.timestamp),
    providerIdx: index('usage_provider_idx').on(table.provider),
  })
);
