/** Pure helpers behind the MCP server form: the textarea ⇄ `args` translation, the
 *  key/value rows that stand in for write-only secrets, and the error text.
 *
 *  Everything here is a pure function of its arguments — there is no JS test runner in
 *  this repo, so the invariants each one has to hold are stated above it and the callers
 *  are written to depend on nothing else.
 */

import { ApiError } from '@/lib/api';

/** One environment variable or header.
 *
 *  Three pieces of state, deliberately kept apart:
 *    - `savedName` is an immutable *fact* — the name this row arrived under when the API
 *      holds a value for it, `null` for a row the user added. It survives Replace, which
 *      is the whole point: clicking Replace and then typing nothing must still count as
 *      "a stored secret this write would drop".
 *    - `replacing` is transient *intent* — the user asked for an input to type a new
 *      value into. It says nothing about what is stored.
 *    - `value` is what will actually be sent, and only a non-empty one ever is.
 */
export interface SecretRow {
  /** Stable for the life of the row: React keys and the field's accessible name. */
  id: string;
  key: string;
  value: string;
  savedName: string | null;
  replacing: boolean;
}

/** Whether the API holds a value for this row. Was a boolean `saved` once; it had to
 *  become the name itself so that renaming a stored row still reports the *old* name. */
export function wasSaved(row: SecretRow): boolean {
  return row.savedName !== null;
}

let rowSeq = 0;

export function newSecretRow(): SecretRow {
  rowSeq += 1;
  return { id: `row-${rowSeq}`, key: '', value: '', savedName: null, replacing: true };
}

/** The rows an existing server starts with: its secret names, values withheld. */
export function rowsFromNames(names: string[]): SecretRow[] {
  return names.map((key) => {
    rowSeq += 1;
    return { id: `row-${rowSeq}`, key, value: '', savedName: key, replacing: false };
  });
}

export function withRow(rows: SecretRow[], index: number, patch: Partial<SecretRow>): SecretRow[] {
  return rows.map((row, i) => (i === index ? { ...row, ...patch } : row));
}

/** Rows → the `env` / `headers` object a write carries. Only a row with a typed value
 *  contributes; a stored-but-untouched one has nothing to send.
 *
 *  INVARIANT (relied on by the dialog): every stored secret this result would drop is
 *  named by `unfilledNames` on the same rows, so a config write can never silently lose
 *  one — the warning that lists them is shown from exactly the same predicate.
 */
export function secretsFromRows(rows: SecretRow[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const row of rows) {
    const key = row.key.trim();
    if (key && row.value.length > 0) out[key] = row.value;
  }
  return out;
}

/** The stored names a config write would drop: the value was never re-entered, or the
 *  row was renamed so the old name disappears either way.
 *
 *  A row the user *deleted* is absent from `rows` and so is not listed — deleting is an
 *  explicit "remove this", not an accident worth warning about.
 */
export function unfilledNames(rows: SecretRow[]): string[] {
  const dropped: string[] = [];
  for (const row of rows) {
    const name = row.savedName;
    if (name === null) continue;
    const sending = row.key.trim() === name && row.value.length > 0;
    if (!sending) dropped.push(name);
  }
  return dropped;
}

// ─── Arguments ──────────────────────────────────────────────────────────────────────

/** Arguments, strictly one per line, taken verbatim.
 *
 *  No splitting on spaces and no per-line trim: `--prompt=hello world` is one argument
 *  and stays one. Only *trailing* blank lines are dropped, so the textarea's final
 *  newline is not an empty argument.
 *
 *  INVARIANT: `parseArgs(formatArgs(args))` is `args` for any argument list without a
 *  trailing empty string (an argument cannot contain a newline in this notation).
 */
export function parseArgs(text: string): string[] {
  const lines = text.split(/\r?\n/);
  while (lines.length > 0 && lines[lines.length - 1].trim() === '') lines.pop();
  return lines;
}

/** What a *new* server's textarea means: `parseArgs`, except that a single line is split
 *  on whitespace — pasting `mcp-server-time --local-timezone=UTC` should not become one
 *  impossible argument.
 *
 *  Never used when editing: there, splitting would rewrite a stored `args` the user only
 *  looked at.
 */
export function parseArgsLenient(text: string): string[] {
  const lines = parseArgs(text);
  if (lines.length > 1) return lines;
  return (lines[0] ?? '').split(/\s+/).filter(Boolean);
}

/** The canonical textarea text for a stored `args`. Comparing the textarea against this
 *  string is how the dialog decides whether the arguments changed — parsing both sides
 *  would call an untouched field dirty the moment the notations disagreed. */
export function formatArgs(args: string[]): string {
  return args.join('\n');
}

// ─── Errors ─────────────────────────────────────────────────────────────────────────

/** The naming rule in words. Shown under the field as you type, and substituted for the
 *  API's own rejection, which is the raw regex — nobody reads a regex. */
export const NAME_HINT =
  "The name must be 2–31 characters: lowercase letters, digits, '-' or '_', starting with a letter or digit.";

/** What went wrong, in the API's own words: a per-field issue when there is one, the
 *  `detail` sentence of a 400/409 otherwise. A pattern violation is rewritten into the
 *  sentence the form already shows under the field. */
export function apiMessage(e: unknown, fallback: string): string {
  if (e instanceof ApiError) {
    const first = e.issues[0];
    if (first) {
      if (/match pattern/i.test(first.message)) return NAME_HINT;
      return first.path ? `${first.path}: ${first.message}` : first.message;
    }
    return e.detail || e.message || fallback;
  }
  return e instanceof Error ? e.message : fallback;
}
