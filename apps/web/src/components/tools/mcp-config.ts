/** Pure helpers behind the MCP server form: the textarea ⇄ array translation, the
 *  key/value rows that stand in for write-only secrets, and the error text. */

import { ApiError } from '@/lib/api';

/** One environment variable or header.
 *
 *  `saved: true` means the *name* came back from the API and the value is stored
 *  server-side — it is never readable, so the row shows "set" until it is replaced. */
export interface SecretRow {
  key: string;
  value: string;
  saved: boolean;
}

/** Arguments, typed either one per line or space-separated on a single line. Multi-line
 *  wins so that an argument containing a space (a prompt, a path) can still be given. */
export function parseArgs(text: string): string[] {
  const lines = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  if (lines.length > 1) return lines;
  return (lines[0] ?? '').split(/\s+/).filter(Boolean);
}

export function formatArgs(args: string[]): string {
  return args.join('\n');
}

/** The rows an existing server starts with: its secret names, values withheld. */
export function rowsFromNames(names: string[]): SecretRow[] {
  return names.map((key) => ({ key, value: '', saved: true }));
}

/** Rows → the `env` / `headers` object a write carries. Only rows with a typed value
 *  make it: a `saved` row has nothing to send, which is exactly why `unfilledNames`
 *  exists to warn about the ones that would be dropped. */
export function secretsFromRows(rows: SecretRow[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const row of rows) {
    const key = row.key.trim();
    if (key && row.value.length > 0) out[key] = row.value;
  }
  return out;
}

/** Names whose stored value was not re-entered. The API replaces a config wholesale, so
 *  any write that carries a config loses these. */
export function unfilledNames(rows: SecretRow[]): string[] {
  return rows.filter((row) => row.saved && row.value.length === 0 && row.key.trim()).map((r) => r.key);
}

export function withRow(rows: SecretRow[], index: number, patch: Partial<SecretRow>): SecretRow[] {
  return rows.map((row, i) => (i === index ? { ...row, ...patch } : row));
}

/** What went wrong, in the API's own words: a per-field issue when there is one, the
 *  `detail` sentence of a 400/409 otherwise. */
export function apiMessage(e: unknown, fallback: string): string {
  if (e instanceof ApiError) {
    const first = e.issues[0];
    if (first) return first.path ? `${first.path}: ${first.message}` : first.message;
    return e.detail || e.message || fallback;
  }
  return e instanceof Error ? e.message : fallback;
}
