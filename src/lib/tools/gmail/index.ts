import 'server-only';

import type { Tool, ToolResult, ToolSchema } from '@/lib/tools/types';
import { gmailFetch } from '@/lib/tools/gmail/client';
import { loadCreds } from '@/lib/tools/gmail/oauth';

const MAX_RESULT_CHARS = 12_000;

function cap(text: string): string {
  return text.length > MAX_RESULT_CHARS ? text.slice(0, MAX_RESULT_CHARS) + '\n…[truncated]' : text;
}

function asString(v: unknown): string | undefined {
  return typeof v === 'string' ? v : undefined;
}
function asNumber(v: unknown): number | undefined {
  return typeof v === 'number' && Number.isFinite(v) ? v : undefined;
}
function asStringArray(v: unknown): string[] | undefined {
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : undefined;
}

const schemas: ToolSchema[] = [
  {
    type: 'function',
    function: {
      name: 'gmail_search',
      description:
        'Search the authenticated user\'s Gmail using Gmail query syntax: from:, to:, subject:, label:INBOX, is:unread, has:attachment, newer_than:1d, older_than:7d, after:YYYY/MM/DD, before:YYYY/MM/DD. ' +
        'IMPORTANT: dates MUST be concrete YYYY/MM/DD (Gmail does NOT understand the words "today", "yesterday" or "now"). Compute the date yourself from the system date provided in the system prompt. ' +
        'Example for "today\'s emails": after:2026/05/31 OR newer_than:1d. ' +
        'Returns matching message ids and short metadata.',
      parameters: {
        type: 'object',
        properties: {
          query: { type: 'string', description: 'Gmail search query (same syntax as the search bar in Gmail).' },
          max_results: { type: 'number', description: 'Max messages to return (1-100, default 25).' },
        },
        required: ['query'],
        additionalProperties: false,
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'gmail_get',
      description: 'Fetch a single Gmail message (subject, from, to, date, text body) by id.',
      parameters: {
        type: 'object',
        properties: { id: { type: 'string', description: 'Message id from gmail_search.' } },
        required: ['id'],
        additionalProperties: false,
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'gmail_send',
      description: 'Send an email from the authenticated user\'s Gmail account.',
      parameters: {
        type: 'object',
        properties: {
          to: { type: 'string', description: 'Recipient email address (comma-separated for multiple).' },
          subject: { type: 'string', description: 'Subject line.' },
          body: { type: 'string', description: 'Plain text body.' },
          cc: { type: 'string', description: 'CC recipients (comma-separated).' },
          bcc: { type: 'string', description: 'BCC recipients (comma-separated).' },
        },
        required: ['to', 'subject', 'body'],
        additionalProperties: false,
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'gmail_modify',
      description: 'Add or remove Gmail labels on a message (use INBOX, STARRED, IMPORTANT, UNREAD, TRASH or custom label ids).',
      parameters: {
        type: 'object',
        properties: {
          id: { type: 'string', description: 'Message id.' },
          add_labels: { type: 'array', items: { type: 'string' }, description: 'Label ids to add.' },
          remove_labels: { type: 'array', items: { type: 'string' }, description: 'Label ids to remove.' },
        },
        required: ['id'],
        additionalProperties: false,
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'gmail_mark_read',
      description: 'Mark a Gmail message as read or unread.',
      parameters: {
        type: 'object',
        properties: {
          id: { type: 'string', description: 'Message id.' },
          read: { type: 'boolean', description: 'true to mark read, false to mark unread.' },
        },
        required: ['id', 'read'],
        additionalProperties: false,
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'gmail_trash',
      description: 'Move a Gmail message to trash (recoverable for 30 days).',
      parameters: {
        type: 'object',
        properties: { id: { type: 'string', description: 'Message id.' } },
        required: ['id'],
        additionalProperties: false,
      },
    },
  },
];

interface GmailHeader { name: string; value: string }
interface GmailPart { mimeType?: string; body?: { data?: string; size?: number }; parts?: GmailPart[]; headers?: GmailHeader[] }
interface GmailMessage { id: string; threadId?: string; snippet?: string; payload?: GmailPart; internalDate?: string; labelIds?: string[] }

function header(headers: GmailHeader[] | undefined, name: string): string {
  return headers?.find((h) => h.name.toLowerCase() === name.toLowerCase())?.value ?? '';
}

function b64UrlDecode(s: string): string {
  return Buffer.from(s.replace(/-/g, '+').replace(/_/g, '/'), 'base64').toString('utf8');
}

/** Walk a Gmail message payload and pull the first text/plain (or text/html fallback) body. */
function extractBody(part: GmailPart | undefined): string {
  if (!part) return '';
  if (part.mimeType === 'text/plain' && part.body?.data) return b64UrlDecode(part.body.data);
  if (part.parts) {
    for (const p of part.parts) {
      const t = extractBody(p);
      if (t) return t;
    }
  }
  if (part.mimeType === 'text/html' && part.body?.data) {
    // Strip HTML tags as a last resort.
    return b64UrlDecode(part.body.data).replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
  }
  return '';
}

async function gmailSearch(args: Record<string, unknown>, signal: AbortSignal): Promise<ToolResult> {
  const query = asString(args.query);
  if (!query) return { ok: false, content: 'gmail_search requires a "query" string.' };
  const max = Math.min(Math.max(asNumber(args.max_results) ?? 25, 1), 100);
  const url = `/users/me/messages?maxResults=${max}&q=${encodeURIComponent(query)}`;
  const res = await gmailFetch(url, { method: 'GET' }, signal);
  if (!res.ok) return { ok: false, content: `gmail_search HTTP ${res.status}: ${cap(await res.text())}` };
  const data = (await res.json()) as { messages?: { id: string; threadId: string }[]; resultSizeEstimate?: number };
  const messages = data.messages ?? [];
  if (messages.length === 0) return { ok: true, content: 'No messages matched.' };

  // Fetch metadata (subject + from) in parallel for the first batch.
  const metas = await Promise.all(
    messages.slice(0, max).map(async (m) => {
      const mr = await gmailFetch(
        `/users/me/messages/${m.id}?format=metadata&metadataHeaders=Subject&metadataHeaders=From&metadataHeaders=Date`,
        { method: 'GET' },
        signal
      );
      if (!mr.ok) return { id: m.id, error: `HTTP ${mr.status}` };
      const j = (await mr.json()) as GmailMessage;
      return {
        id: m.id,
        from: header(j.payload?.headers, 'From'),
        subject: header(j.payload?.headers, 'Subject'),
        date: header(j.payload?.headers, 'Date'),
        snippet: j.snippet ?? '',
      };
    })
  );
  const text = metas
    .map((m, i) =>
      'error' in m
        ? `${i + 1}. [${m.id}] (${m.error})`
        : `${i + 1}. [${m.id}] ${m.subject || '(no subject)'}\n   from: ${m.from}\n   date: ${m.date}\n   ${m.snippet}`
    )
    .join('\n\n');
  return { ok: true, content: cap(text) };
}

async function gmailGet(args: Record<string, unknown>, signal: AbortSignal): Promise<ToolResult> {
  const id = asString(args.id);
  if (!id) return { ok: false, content: 'gmail_get requires an "id" string.' };
  const res = await gmailFetch(`/users/me/messages/${id}?format=full`, { method: 'GET' }, signal);
  if (!res.ok) return { ok: false, content: `gmail_get HTTP ${res.status}: ${cap(await res.text())}` };
  const j = (await res.json()) as GmailMessage;
  const out = [
    `Subject: ${header(j.payload?.headers, 'Subject')}`,
    `From: ${header(j.payload?.headers, 'From')}`,
    `To: ${header(j.payload?.headers, 'To')}`,
    `Date: ${header(j.payload?.headers, 'Date')}`,
    `Labels: ${(j.labelIds ?? []).join(', ')}`,
    '',
    extractBody(j.payload) || j.snippet || '',
  ].join('\n');
  return { ok: true, content: cap(out) };
}

function buildRfc5322(to: string, subject: string, body: string, cc?: string, bcc?: string): string {
  const lines = [
    `To: ${to}`,
    cc ? `Cc: ${cc}` : '',
    bcc ? `Bcc: ${bcc}` : '',
    `Subject: ${subject}`,
    'MIME-Version: 1.0',
    'Content-Type: text/plain; charset=utf-8',
    '',
    body,
  ].filter(Boolean);
  return lines.join('\r\n');
}

async function gmailSend(args: Record<string, unknown>, signal: AbortSignal): Promise<ToolResult> {
  const to = asString(args.to);
  const subject = asString(args.subject);
  const body = asString(args.body);
  if (!to || !subject || body == null) {
    return { ok: false, content: 'gmail_send requires "to", "subject", and "body".' };
  }
  const raw = Buffer.from(
    buildRfc5322(to, subject, body, asString(args.cc), asString(args.bcc)),
    'utf8'
  ).toString('base64').replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  const res = await gmailFetch(
    '/users/me/messages/send',
    { method: 'POST', body: JSON.stringify({ raw }) },
    signal
  );
  if (!res.ok) return { ok: false, content: `gmail_send HTTP ${res.status}: ${cap(await res.text())}` };
  const j = (await res.json()) as { id: string };
  return { ok: true, content: `Sent. id=${j.id}` };
}

async function gmailModify(args: Record<string, unknown>, signal: AbortSignal): Promise<ToolResult> {
  const id = asString(args.id);
  if (!id) return { ok: false, content: 'gmail_modify requires an "id".' };
  const add = asStringArray(args.add_labels) ?? [];
  const rem = asStringArray(args.remove_labels) ?? [];
  if (add.length === 0 && rem.length === 0) return { ok: false, content: 'gmail_modify requires add_labels or remove_labels.' };
  const res = await gmailFetch(
    `/users/me/messages/${id}/modify`,
    { method: 'POST', body: JSON.stringify({ addLabelIds: add, removeLabelIds: rem }) },
    signal
  );
  if (!res.ok) return { ok: false, content: `gmail_modify HTTP ${res.status}: ${cap(await res.text())}` };
  return { ok: true, content: `Modified ${id}. add=${add.join(',') || '-'} remove=${rem.join(',') || '-'}` };
}

async function gmailMarkRead(args: Record<string, unknown>, signal: AbortSignal): Promise<ToolResult> {
  const id = asString(args.id);
  const read = typeof args.read === 'boolean' ? args.read : undefined;
  if (!id || read === undefined) return { ok: false, content: 'gmail_mark_read requires "id" and boolean "read".' };
  return gmailModify({ id, add_labels: read ? [] : ['UNREAD'], remove_labels: read ? ['UNREAD'] : [] }, signal);
}

async function gmailTrash(args: Record<string, unknown>, signal: AbortSignal): Promise<ToolResult> {
  const id = asString(args.id);
  if (!id) return { ok: false, content: 'gmail_trash requires an "id".' };
  const res = await gmailFetch(`/users/me/messages/${id}/trash`, { method: 'POST' }, signal);
  if (!res.ok) return { ok: false, content: `gmail_trash HTTP ${res.status}: ${cap(await res.text())}` };
  return { ok: true, content: `Trashed ${id}.` };
}

const DISPATCH: Record<string, (args: Record<string, unknown>, signal: AbortSignal) => Promise<ToolResult>> = {
  gmail_search: gmailSearch,
  gmail_get: gmailGet,
  gmail_send: gmailSend,
  gmail_modify: gmailModify,
  gmail_mark_read: gmailMarkRead,
  gmail_trash: gmailTrash,
};

export const gmailTool: Tool = {
  name: 'gmail',
  label: 'Gmail',
  description: 'Read, send, label, and trash Gmail messages (gmail_search/get/send/modify/mark_read/trash).',
  schemas,
  setupUrl: '/api/tools/gmail/oauth/start',
  async isConfigured() {
    return (await loadCreds()) != null;
  },
  async execute(name, args, signal) {
    const fn = DISPATCH[name];
    if (!fn) return { ok: false, content: `Unknown gmail function: ${name}` };
    try {
      return await fn(args, signal);
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Gmail call failed.';
      return { ok: false, content: `Error: ${msg}` };
    }
  },
};
