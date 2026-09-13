/** Which step inputs the AI has no honest way of filling in.
 *
 *  "Ask AI" is for values the model can *derive* from the context it is given: a subject
 *  line, a summary, a date phrased in words. It is not for opaque identifiers — a Discord
 *  `channel_id`, a Notion `page_id`, a Slack `thread_ts`. Asked for one of those with
 *  nothing in the run to read it off, the model does the only thing it can: it makes one
 *  up. `123456789012345678` fails the call; a fabricated id that happens to exist
 *  somewhere else posts the message to the wrong place and reports success.
 *
 *  The one honest case is an identifier an *earlier step already returned* — the model is
 *  then choosing from a real list rather than inventing. So this module answers two
 *  questions: does this field hold an opaque identifier (from its schema alone, because
 *  MCP servers declare their own), and could anything before this step supply it.
 *
 *  Pure functions — no React. */

import type { AutomationStep, Catalog, RunDetail } from '@/lib/automations/types';
import { stepOutput } from './samples';
import { enumOptions, schemaType, type JsonSchema } from './schema';
import { stepOutputShape } from './step-output-shape';

/** Why "Ask AI" is off for this field. One wording, shared by the disabled segment's
 *  tooltip and the warning under a field that is already in `ai` mode. */
export const OPAQUE_AI_REASON =
  "The AI can't invent an identifier. Pick it from an earlier step, or paste it here.";

/** Shown under the instruction box when the field *is* an identifier but an earlier step
 *  could plausibly hold it — the AI is choosing, not guessing, and should be told where
 *  to choose from. */
export const OPAQUE_AI_STEP_HINT =
  'Name the earlier step this should come from — the AI can only choose from what previous steps returned.';

// ─── the field name ─────────────────────────────────────────────────────────────────

/** `id`, `ids`. */
const ID_NAME = /^ids?$/i;
/** `channel_id`, `label_ids`. */
const ID_SUFFIX = /_ids?$/i;
/** `channelId`, `pageIDs` — a real camel hump, so `valid` / `uuid` / `grid` don't match. */
const ID_CAMEL = /[a-z0-9](?:Id|ID)s?$/;
/** Slack message / thread timestamps, which are identifiers in everything but name. */
const TS_NAME = /^ts$/i;
const TS_SUFFIX = /_ts$/i;
const TS_CAMEL = /[a-z0-9]Ts$/;

/** `ID` as a word — deliberately case-sensitive, so the "id" inside ordinary prose
 *  ("a valid identifier is…", "consider") can't trip it. `identifier` and `snowflake`
 *  carry their own meaning and match either way. */
const ID_PHRASE = /\bID\b/;
const ID_WORD = /\b(?:identifiers?|snowflakes?)\b/i;

/** Does the name alone read as an identifier? */
export function looksLikeIdentifierName(name: string): boolean {
  return (
    ID_NAME.test(name) ||
    ID_SUFFIX.test(name) ||
    ID_CAMEL.test(name) ||
    TS_NAME.test(name) ||
    TS_SUFFIX.test(name) ||
    TS_CAMEL.test(name)
  );
}

/** What the identifier is *of*: `channel_id` → `channel`, `thread_ts` → `thread`.
 *  `''` when the name is nothing but the suffix (`id`), or the stem is too short to
 *  match anything without producing noise. */
export function identifierStem(name: string): string {
  let stem = name.replace(/_(?:ids?|ts)$/i, '');
  if (stem === name) stem = name.replace(/([a-z0-9])(?:Id|ID|Ts)s?$/, '$1');
  if (ID_NAME.test(stem) || TS_NAME.test(stem)) return '';
  return stem.length >= 3 ? stem : '';
}

function asString(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

/** Is this field an opaque identifier — something the model would have to invent?
 *
 *  Conservative on purpose. A field named `channel` (not `channel_id`) is *not* opaque:
 *  Slack's own `slack_send_message` resolves `#general` for you, and a human name is
 *  exactly the kind of thing the AI can derive. An `enum` is never opaque either — the
 *  choices are right there in the schema, so picking one is not guessing. And only
 *  single scalar fields qualify; an object or a list is a different shaped problem. */
export function isOpaqueIdentifier(name: string, schema: JsonSchema | null | undefined): boolean {
  const field = schema ?? {};
  if (enumOptions(field).length > 0) return false;
  const type = schemaType(field);
  if (type !== 'string' && type !== 'integer' && type !== 'number') return false;
  if (looksLikeIdentifierName(name)) return true;
  const description = asString(field.description);
  return ID_PHRASE.test(description) || ID_WORD.test(description);
}

// ─── could anything earlier hold it? ────────────────────────────────────────────────

const PATH_TOKEN_RE = /[A-Za-z0-9_]+/g;

/** The last name in a path: `.channels[0].id` → `id`. */
function leafName(path: string): string {
  const tokens = path.match(PATH_TOKEN_RE);
  return tokens && tokens.length > 0 ? tokens[tokens.length - 1] : '';
}

/** A leaf that is itself a Slack-style timestamp — only ever a match for a `_ts` field;
 *  a `channel_id` is not served by somebody else's `ts`. */
const TS_LEAF = /^ts$|_ts$|[a-z0-9]Ts$/;

/** Could this output row be the identifier we're after? Loose by design: the answer only
 *  ever decides whether to *keep* "Ask AI" available, so a near-miss costs nothing and a
 *  false "impossible" would take away a mode that works.
 *
 *  Three ways to match: the row is plainly an id (`id`, `channel_id`, `message_id`), the
 *  row is a timestamp and the field wants one, or the row is named after the thing the id
 *  identifies — `channel_id` and a `channels` array, which is how `slack_list_channels`
 *  feeds `slack_send_message`. */
function rowSupplies(path: string, label: string, stem: string, wantsTs: boolean): boolean {
  const leaf = leafName(path);
  // The whole-result row (`path: ''`) names nothing; it is the object, not a value.
  if (leaf.length === 0) return false;
  if (leaf.toLowerCase().includes('id')) return true;
  if (wantsTs && TS_LEAF.test(leaf)) return true;
  if (stem.length === 0) return false;
  return `${path} ${label}`.toLowerCase().includes(stem.toLowerCase());
}

/** The steps strictly before `stepId` — the only ones a reference may point at.
 *  A step id that isn't in the document leaves every step on offer rather than none:
 *  the same way `ReferencePicker` reads a missing bound. */
export function stepsBefore(steps: AutomationStep[], stepId: string): AutomationStep[] {
  const cut = steps.findIndex((s) => s.id === stepId);
  return cut === -1 ? steps : steps.slice(0, cut);
}

/** Could an earlier step plausibly hand this field its identifier?
 *
 *  True when some earlier step offers a row that looks like the id (a leaf containing
 *  `id`, or anything named after the thing the id identifies), **or** when an earlier
 *  step's output shape is simply unknown — an action nobody has run and nobody declares
 *  an `outputSchema` for could return anything at all, and "we don't know" must never be
 *  reported to the user as "impossible". */
export function canEarlierStepSupply(
  name: string,
  earlier: AutomationStep[],
  catalog: Catalog | null,
  run: RunDetail | null | undefined
): boolean {
  const stem = identifierStem(name);
  const wantsTs = TS_NAME.test(name) || TS_SUFFIX.test(name) || TS_CAMEL.test(name);
  return earlier.some((step) => {
    const shape = stepOutputShape(step, catalog, stepOutput(run, step.id), '');
    if (shape.source === 'none') return true;
    return shape.rows.some((row) => rowSupplies(row.path, row.label, stem, wantsTs));
  });
}

/** What the field-value input needs to know about one field, in one pass.
 *  `block` is the reason "Ask AI" is unavailable, or `null` when it is fine. */
export interface OpaqueFieldState {
  opaque: boolean;
  block: string | null;
}

export function opaqueFieldState(
  name: string,
  schema: JsonSchema | null | undefined,
  steps: AutomationStep[],
  stepId: string,
  catalog: Catalog | null,
  run: RunDetail | null | undefined
): OpaqueFieldState {
  if (!isOpaqueIdentifier(name, schema)) return { opaque: false, block: null };
  const earlier = stepsBefore(steps, stepId);
  const supplied = canEarlierStepSupply(name, earlier, catalog, run);
  return { opaque: true, block: supplied ? null : OPAQUE_AI_REASON };
}
