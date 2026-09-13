"use strict";
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
Object.defineProperty(exports, "__esModule", { value: true });
exports.OPAQUE_AI_STEP_HINT = exports.OPAQUE_AI_REASON = void 0;
exports.looksLikeIdentifierName = looksLikeIdentifierName;
exports.identifierStem = identifierStem;
exports.isOpaqueIdentifier = isOpaqueIdentifier;
exports.stepsBefore = stepsBefore;
exports.canEarlierStepSupply = canEarlierStepSupply;
exports.opaqueFieldState = opaqueFieldState;
const samples_1 = require("./samples");
const schema_1 = require("./schema");
const step_output_shape_1 = require("./step-output-shape");
/** Why "Ask AI" is off for this field. One wording, shared by the disabled segment's
 *  tooltip and the warning under a field that is already in `ai` mode. */
exports.OPAQUE_AI_REASON = "The AI can't invent an identifier. Pick it from an earlier step, or paste it here.";
/** Shown under the instruction box when the field *is* an identifier but an earlier step
 *  could plausibly hold it — the AI is choosing, not guessing, and should be told where
 *  to choose from. */
exports.OPAQUE_AI_STEP_HINT = 'Name the earlier step this should come from — the AI can only choose from what previous steps returned.';
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
function looksLikeIdentifierName(name) {
    return (ID_NAME.test(name) ||
        ID_SUFFIX.test(name) ||
        ID_CAMEL.test(name) ||
        TS_NAME.test(name) ||
        TS_SUFFIX.test(name) ||
        TS_CAMEL.test(name));
}
/** What the identifier is *of*: `channel_id` → `channel`, `thread_ts` → `thread`.
 *  `''` when the name is nothing but the suffix (`id`), or the stem is too short to
 *  match anything without producing noise. */
function identifierStem(name) {
    let stem = name.replace(/_(?:ids?|ts)$/i, '');
    if (stem === name)
        stem = name.replace(/([a-z0-9])(?:Id|ID|Ts)s?$/, '$1');
    if (ID_NAME.test(stem) || TS_NAME.test(stem))
        return '';
    return stem.length >= 3 ? stem : '';
}
function asString(value) {
    return typeof value === 'string' ? value : '';
}
/** Is this field an opaque identifier — something the model would have to invent?
 *
 *  Conservative on purpose. A field named `channel` (not `channel_id`) is *not* opaque:
 *  Slack's own `slack_send_message` resolves `#general` for you, and a human name is
 *  exactly the kind of thing the AI can derive. An `enum` is never opaque either — the
 *  choices are right there in the schema, so picking one is not guessing. And only
 *  single scalar fields qualify; an object or a list is a different shaped problem. */
function isOpaqueIdentifier(name, schema) {
    const field = schema ?? {};
    if ((0, schema_1.enumOptions)(field).length > 0)
        return false;
    const type = (0, schema_1.schemaType)(field);
    if (type !== 'string' && type !== 'integer' && type !== 'number')
        return false;
    if (looksLikeIdentifierName(name))
        return true;
    const description = asString(field.description);
    return ID_PHRASE.test(description) || ID_WORD.test(description);
}
// ─── could anything earlier hold it? ────────────────────────────────────────────────
const PATH_TOKEN_RE = /[A-Za-z0-9_]+/g;
/** The last name in a path: `.channels[0].id` → `id`. */
function leafName(path) {
    const tokens = path.match(PATH_TOKEN_RE);
    return tokens && tokens.length > 0 ? tokens[tokens.length - 1] : '';
}
/** Could this output row be the identifier we're after? Loose by design: the answer only
 *  ever decides whether to *keep* "Ask AI" available, so a near-miss costs nothing and a
 *  false "impossible" would take away a mode that works. */
function rowSupplies(path, label, stem) {
    const leaf = leafName(path);
    // The whole-result row (`path: ''`) names nothing; it is the object, not a value.
    if (leaf.length === 0)
        return false;
    if (leaf.toLowerCase().includes('id'))
        return true;
    if (stem.length === 0)
        return false;
    return `${path} ${label}`.toLowerCase().includes(stem.toLowerCase());
}
/** The steps strictly before `stepId` — the only ones a reference may point at.
 *  A step id that isn't in the document leaves every step on offer rather than none:
 *  the same way `ReferencePicker` reads a missing bound. */
function stepsBefore(steps, stepId) {
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
function canEarlierStepSupply(name, earlier, catalog, run) {
    const stem = identifierStem(name);
    return earlier.some((step) => {
        const shape = (0, step_output_shape_1.stepOutputShape)(step, catalog, (0, samples_1.stepOutput)(run, step.id), '');
        if (shape.source === 'none')
            return true;
        return shape.rows.some((row) => rowSupplies(row.path, row.label, stem));
    });
}
function opaqueFieldState(name, schema, steps, stepId, catalog, run) {
    if (!isOpaqueIdentifier(name, schema))
        return { opaque: false, block: null };
    const earlier = stepsBefore(steps, stepId);
    const supplied = canEarlierStepSupply(name, earlier, catalog, run);
    return { opaque: true, block: supplied ? null : exports.OPAQUE_AI_REASON };
}
