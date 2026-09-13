/** TypeScript mirror of the automation document language and the `/api/automations` +
 *  `/api/tools` payloads.
 *
 *  Two casings live side by side, on purpose — they mirror the backend exactly:
 *    - the **document** (and the `Operation`s applied to it) is snake_case, because it is a
 *      stored interchange format read/written verbatim (`app.schemas.documents`);
 *    - the **API envelope** around it is camelCase (`app.schemas.automations`, `APISchema`).
 *
 *  Keep this file free of React/store imports: it is the shared vocabulary for the API
 *  client, the store, the canvas and the inspector.
 */

import type { Provider } from '@/lib/types';

// ─── Document: field values ─────────────────────────────────────────────────────────

/** One input slot of an action step. `literal` carries the value itself, `ref` a
 *  `{{ step_x.output }}` template string, `ai` a natural-language instruction the
 *  executor resolves with the model. */
export interface FieldValue {
  kind: 'literal' | 'ref' | 'ai';
  value?: unknown;
}

export interface RetryPolicy {
  max_attempts: number;
  backoff_seconds: number;
}

// ─── Document: step settings ────────────────────────────────────────────────────────

export interface ActionSettings {
  integration: string;
  action: string;
  input: Record<string, FieldValue>;
}

export interface AiOutput {
  mode: 'text' | 'json';
  /** JSON schema, only meaningful when `mode === 'json'`. Named `schema` in the document. */
  schema?: Record<string, unknown> | null;
}

export interface AiStepSettings {
  instructions: string;
  /** Catalog action names the AI step may call (see `Catalog`). */
  tools: string[];
  output: AiOutput;
}

export type ConditionOp =
  | 'eq'
  | 'neq'
  | 'contains'
  | 'not_contains'
  | 'gt'
  | 'gte'
  | 'lt'
  | 'lte'
  | 'is_empty'
  | 'is_not_empty'
  | 'is_true'
  | 'is_false';

/** Ops that take no `right` operand. */
export const UNARY_CONDITION_OPS: readonly ConditionOp[] = [
  'is_empty',
  'is_not_empty',
  'is_true',
  'is_false',
];

export interface Condition {
  left: FieldValue;
  op: ConditionOp;
  right?: FieldValue | null;
}

export interface Rules {
  combinator: 'and' | 'or';
  conditions: Condition[];
}

export type FilterSettings =
  | { mode: 'rules'; rules: Rules; instruction?: null }
  | { mode: 'ai'; instruction: string; rules?: null };

// ─── Document: steps ────────────────────────────────────────────────────────────────

interface StepBase {
  /** `step_` + at least 5 lowercase base36 chars — see `newStepId`. */
  id: string;
  name: string;
  retry?: RetryPolicy | null;
  timeout_seconds?: number | null;
  /** Server-computed: false when the step has error-level issues. */
  valid: boolean;
}

export interface ActionStep extends StepBase {
  type: 'action';
  settings: ActionSettings;
}

export interface AiStep extends StepBase {
  type: 'ai';
  settings: AiStepSettings;
}

export interface FilterStep extends StepBase {
  type: 'filter';
  settings: FilterSettings;
}

export type AutomationStep = ActionStep | AiStep | FilterStep;
export type StepType = AutomationStep['type'];

// ─── Document: trigger + meta ───────────────────────────────────────────────────────

export type ScheduleSettings =
  | { mode: 'cron'; cron: string; timezone?: string | null; every_minutes?: null }
  | { mode: 'interval'; every_minutes: number; timezone?: string | null; cron?: null };

export interface ManualTrigger {
  type: 'manual';
}

export interface ScheduleTrigger {
  type: 'schedule';
  settings: ScheduleSettings;
}

export type Trigger = ManualTrigger | ScheduleTrigger;

export interface ModelRef {
  provider: Provider;
  model: string;
}

export interface AutomationDocument {
  name: string;
  description?: string;
  model: ModelRef;
  trigger: Trigger;
  steps: AutomationStep[];
}

// ─── Operations (snake_case, `POST /automations/{id}/operations`) ───────────────────

/** Top-level step fields an `update_step` may patch. `settings` is merged one level
 *  deep by the backend, every other key overwrites. `id` is rejected. */
export interface StepPatch {
  name?: string;
  retry?: RetryPolicy | null;
  timeout_seconds?: number | null;
  settings?: Record<string, unknown>;
  [key: string]: unknown;
}

export type Operation =
  | { op: 'add_step'; step: AutomationStep; index?: number }
  | { op: 'update_step'; step_id: string; patch: StepPatch }
  | { op: 'remove_step'; step_id: string }
  | { op: 'move_step'; step_id: string; index: number }
  | { op: 'set_trigger'; trigger: Trigger }
  | { op: 'set_meta'; name?: string; description?: string; model?: ModelRef };

// ─── API envelope (camelCase) ───────────────────────────────────────────────────────

export type ValidationLevel = 'error' | 'warning';

export interface ValidationIssue {
  path: string;
  message: string;
  level: ValidationLevel;
}

export interface LastRunPayload {
  status: string;
  endedAt: number | null;
}

export interface AutomationSummary {
  id: string;
  name: string;
  enabled: boolean;
  /** Server-rendered trigger phrase — same wording as `describeTrigger` below. */
  triggerSummary: string;
  nextRunAt: number | null;
  lastRun: LastRunPayload | null;
  valid: boolean;
  updatedAt: number;
}

export interface AutomationDetail {
  id: string;
  name: string;
  enabled: boolean;
  document: AutomationDocument;
  versionNumber: number;
  issues: ValidationIssue[];
  nextRunAt: number | null;
  /** The builder assistant's transcript, oldest first. */
  assistantMessages: AssistantMessage[];
  lastRun: LastRunPayload | null;
  createdAt: number;
  updatedAt: number;
}

/** Shape returned by every document write (PUT, /operations, version restore). */
export interface DocumentWriteResult {
  document: AutomationDocument;
  issues: ValidationIssue[];
  versionNumber: number;
  summary: string[];
}

export interface ValidateResult {
  document: AutomationDocument;
  issues: ValidationIssue[];
}

// ─── Assistant ──────────────────────────────────────────────────────────────────────

/** One stored turn of the builder assistant.
 *
 *  `summary`, `runId` and `error` only ever appear on an assistant turn: what its
 *  operations changed (one human sentence each), the test run it started, and — when
 *  its edits were rejected and nothing was applied — why. The index signature is
 *  deliberate: the backend may add fields (an `intent`, say) and an unknown key must
 *  not make the transcript unassignable. */
export interface AssistantMessage {
  role: 'user' | 'assistant';
  content: string;
  /** Epoch milliseconds. */
  ts: number;
  summary?: string[];
  runId?: string | null;
  error?: string | null;
  [key: string]: unknown;
}

/** `POST /automations/{id}/assistant` — one turn.
 *
 *  Carries the same `document`/`issues`/`versionNumber` triple as a document write (the
 *  turn may have edited the document) plus what belongs to the conversation. `error` is
 *  a message to render, not a failed request: it means the assistant's operations were
 *  rejected and nothing was applied. */
export interface AssistantResponse {
  message: string;
  /** Human sentences describing what was applied — empty when nothing was. */
  summary: string[];
  operationsApplied: number;
  runId: string | null;
  document: AutomationDocument;
  issues: ValidationIssue[];
  versionNumber: number;
  /** The whole transcript, including this turn. */
  assistantMessages: AssistantMessage[];
  error: string | null;
}

export type VersionAuthor = 'user' | 'assistant' | 'json' | 'migration' | 'restore';

export interface VersionSummary {
  number: number;
  createdBy: VersionAuthor;
  createdAt: number;
}

export interface VersionDetail extends VersionSummary {
  document: AutomationDocument;
}

// ─── Runs ───────────────────────────────────────────────────────────────────────────

export type RunTrigger = 'manual' | 'schedule' | 'test';
export type RunStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled';
export type RunStepStatus =
  | 'pending'
  | 'running'
  | 'succeeded'
  | 'failed'
  | 'skipped'
  | 'cancelled';

export const TERMINAL_RUN_STATUSES: readonly RunStatus[] = ['succeeded', 'failed', 'cancelled'];
export const ACTIVE_RUN_STATUSES: readonly RunStatus[] = ['queued', 'running'];

export function isRunActive(status: RunStatus | undefined | null): boolean {
  return !!status && (ACTIVE_RUN_STATUSES as readonly string[]).includes(status);
}

export interface RunSummary {
  id: string;
  automationId: string;
  versionNumber: number | null;
  trigger: RunTrigger;
  status: RunStatus;
  stoppedByStepId: string | null;
  error: string | null;
  inputTokens: number;
  outputTokens: number;
  startedAt: number | null;
  endedAt: number | null;
  durationMs: number | null;
  createdAt: number;
}

/** One entry of a step's `trace`: retry attempts and the AI step's tool calls. */
export type TraceEntry =
  | { kind: 'attempt'; n: number; error?: string; retryInSeconds?: number }
  | { kind: 'tool_call'; id: string; tool: string; args?: string }
  | { kind: 'tool_result'; id: string; tool: string; ok?: boolean; result?: string }
  | { kind: string; [key: string]: unknown };

export interface RunStep {
  id: string;
  stepId: string;
  index: number;
  name: string;
  type: string;
  status: RunStepStatus;
  attempt: number;
  resolvedInput: Record<string, unknown> | null;
  output: unknown;
  error: string | null;
  trace: TraceEntry[];
  startedAt: number | null;
  endedAt: number | null;
  durationMs: number | null;
}

export interface RunDetail extends RunSummary {
  steps: RunStep[];
}

/** Events from `GET /automations/{id}/runs/{runId}/events` (data-only SSE, camelCase).
 *  Every step event carries `stepId` + `index`; the stream always opens with `snapshot`
 *  and ends after `run_finished`. */
export type RunEvent =
  | { type: 'snapshot'; run: RunDetail }
  | { type: 'run_started'; runId: string; status: RunStatus }
  | { type: 'step_started'; stepId: string; index: number; attempt: number }
  | {
      type: 'step_retry';
      stepId: string;
      index: number;
      attempt: number;
      error: string;
      retryInSeconds: number;
    }
  | { type: 'step_text'; stepId: string; index: number; delta: string }
  | { type: 'step_tool_call'; stepId: string; index: number; id: string; tool: string; args: string }
  | {
      type: 'step_tool_result';
      stepId: string;
      index: number;
      id: string;
      tool: string;
      ok: boolean;
      result: string;
    }
  | {
      type: 'step_finished';
      stepId: string;
      index: number;
      status: RunStepStatus;
      outputPreview?: string;
      /** Present only when the output is small enough to ride along on the event. */
      output?: unknown;
      error?: string | null;
    }
  | { type: 'run_finished'; runId: string; status: RunStatus; error?: string | null };

// ─── Tool catalog (`GET /api/tools`) ────────────────────────────────────────────────

export interface CredentialField {
  name: string;
  label: string;
  secret: boolean;
  placeholder?: string;
}

export interface SetupStep {
  title: string;
  description?: string;
  link?: { label: string; url: string };
  /** `value` may contain the literal `__ORIGIN__`, substituted client-side. */
  copy?: { label: string; value: string };
  code?: string;
}

export interface ToolSetup {
  intro?: string;
  steps?: SetupStep[];
  note?: string;
}

export interface CatalogAction {
  name: string;
  integration: string;
  label: string;
  description: string;
  inputSchema: Record<string, unknown>;
  outputDescription: string;
  outputSchema: Record<string, unknown> | null;
}

export interface CatalogIntegration {
  name: string;
  label: string;
  description: string;
  logoUrl: string;
  connectMode: 'oauth' | 'config';
  setupUrl: string;
  credentialsNamespace: string | null;
  credentialsFields: CredentialField[];
  setup: ToolSetup;
  connected: boolean;
  actions: CatalogAction[];
}

/** One registered MCP server as the *catalog* sees it (`GET /tools` → `mcpServers[]`).
 *
 *  Deliberately thin: how to reach the server (command, URL, which secrets are set)
 *  belongs to `McpServerView` / `GET /mcp/servers`, which only the Tools page reads.
 *  Here we just need to know which actions exist and whether they can run. */
export interface CatalogMcpServer {
  name: string;
  transport: McpTransport;
  enabled: boolean;
  /** Enabled, synced and not in error — i.e. its actions can be picked right now. */
  connected: boolean;
  lastError: string | null;
  /** Actions named `mcp__<server>__<tool>`, under the `mcp:<server>` integration. */
  actions: CatalogAction[];
}

export interface Catalog {
  integrations: CatalogIntegration[];
  /** Always-available actions with `integration === "builtin"`. */
  builtinActions: CatalogAction[];
  /** Every registered MCP server, disabled ones included — a disabled server still
   *  explains why an existing step's action vanished from the tool list. */
  mcpServers: CatalogMcpServer[];
}

export const BUILTIN_INTEGRATION = 'builtin';

/** Mirrors `app.mcp.schemas.mcp_integration`: every MCP action's `integration`. */
export const MCP_INTEGRATION_PREFIX = 'mcp:';

/** `"mcp:notion"` → `"notion"`; `null` for any other integration name. */
export function mcpServerOf(integration: string): string | null {
  return integration.startsWith(MCP_INTEGRATION_PREFIX)
    ? integration.slice(MCP_INTEGRATION_PREFIX.length)
    : null;
}

export function findCatalogMcpServer(
  catalog: Catalog | null,
  name: string
): CatalogMcpServer | undefined {
  return catalog?.mcpServers?.find((s) => s.name === name);
}

/** Every action in the catalog, integrations first, then builtins, then MCP tools. */
export function catalogActions(catalog: Catalog | null): CatalogAction[] {
  if (!catalog) return [];
  return [
    ...catalog.integrations.flatMap((i) => i.actions),
    ...catalog.builtinActions,
    ...(catalog.mcpServers ?? []).flatMap((s) => s.actions),
  ];
}

export function findCatalogAction(
  catalog: Catalog | null,
  integration: string,
  action: string
): CatalogAction | undefined {
  if (!catalog) return undefined;
  if (integration === BUILTIN_INTEGRATION) {
    return catalog.builtinActions.find((a) => a.name === action);
  }
  const server = mcpServerOf(integration);
  if (server !== null) {
    return findCatalogMcpServer(catalog, server)?.actions.find((a) => a.name === action);
  }
  return catalog.integrations
    .find((i) => i.name === integration)
    ?.actions.find((a) => a.name === action);
}

export function findCatalogIntegration(
  catalog: Catalog | null,
  name: string
): CatalogIntegration | undefined {
  return catalog?.integrations.find((i) => i.name === name);
}

// ─── MCP servers (`/api/mcp/servers`) ───────────────────────────────────────────────

export type McpTransport = 'stdio' | 'http';

/** Mirrors `app.mcp.schemas.SERVER_NAME_RE`. The name becomes part of every tool id the
 *  model sees (`mcp__<name>__<tool>`), so it has to stay a slug. */
export const MCP_SERVER_NAME_RE = /^[a-z0-9][a-z0-9_-]{1,30}$/;

/** One tool as the server advertises it. */
export interface McpToolInfo {
  name: string;
  description: string;
}

/** A registered server as `GET /mcp/servers` returns it.
 *
 *  Secret *values* never come back: `envNames` / `headerNames` are the keys that are
 *  set, which is all the UI needs to render a "set" badge. */
export interface McpServerView {
  id: string;
  name: string;
  transport: McpTransport;
  enabled: boolean;
  allowPrivateNetwork: boolean;
  connected: boolean;
  toolCount: number;
  tools: McpToolInfo[];
  lastError: string | null;
  /** Unix ms, or `null` when the server has never been synced. */
  lastSyncedAt: number | null;
  // stdio
  command: string | null;
  args: string[];
  envNames: string[];
  // http
  url: string | null;
  headerNames: string[];
}

/** The write side of a server: unlike `McpServerView` this one carries the secrets.
 *
 *  The server *replaces* the whole config on every write, so a partial `env` (or a
 *  missing one) clears the values that are not in it — see `McpServerDialog`. */
export type McpServerConfigInput =
  | { command: string; args?: string[]; env?: Record<string, string> }
  | { url: string; headers?: Record<string, string> };

/** A server as it is written. The API also accepts `enabled` on a create; this UI never
 *  sends it — a server is registered on, and the card's switch is how it goes off. */
export interface McpServerInput {
  name: string;
  transport: McpTransport;
  config: McpServerConfigInput;
  allowPrivateNetwork?: boolean;
}

/** `POST /mcp/servers/test` — always a 200: "this config does not work, here is why"
 *  is an answer, not a failure. */
export interface McpTestResult {
  ok: boolean;
  tools: McpToolInfo[];
  error: string | null;
}

// ─── Helpers ────────────────────────────────────────────────────────────────────────

/** Fresh step id in the backend's format (`^step_[a-z0-9]{5,}$`). */
export function newStepId(): string {
  let suffix = '';
  while (suffix.length < 6) {
    suffix += Math.random().toString(36).slice(2);
  }
  return `step_${suffix.slice(0, 6)}`;
}

function cronTime(minute: string, hour: string): string | null {
  if (!/^\d+$/.test(minute) || !/^\d+$/.test(hour)) return null;
  return `${String(Number(hour)).padStart(2, '0')}:${String(Number(minute)).padStart(2, '0')}`;
}

/** A short, lowercase phrase describing a trigger — a verbatim mirror of the backend's
 *  `app.services.documents.diff.describe_trigger`, which is also what feeds
 *  `AutomationSummary.triggerSummary`. Capitalize at the call site for standalone use;
 *  the timezone is deliberately NOT part of the phrase (see `triggerTimezone`). */
export function describeTrigger(trigger: Trigger | undefined | null): string {
  if (!trigger || trigger.type === 'manual') return 'manual trigger';

  const settings = trigger.settings;
  if (settings.mode === 'interval') {
    const n = settings.every_minutes;
    return `every ${n} ${n === 1 ? 'minute' : 'minutes'}`;
  }

  const cron = settings.cron ?? '';
  const parts = cron.split(' ').filter((p) => p.length > 0);
  if (parts.length !== 5) return `cron schedule '${cron}'`;
  const [minute, hour, dom, month, dow] = parts;
  const time = cronTime(minute, hour);
  if (time && dom === '*' && month === '*' && dow === '1-5') return `weekdays at ${time}`;
  if (time && dom === '*' && month === '*' && dow === '*') return `daily at ${time}`;
  return `cron schedule '${cron}'`;
}

/** The trigger's timezone, when it has one — rendered next to `describeTrigger` rather
 *  than inside it, so the phrase stays identical to the server's `triggerSummary`. */
export function triggerTimezone(trigger: Trigger | undefined | null): string | null {
  if (!trigger || trigger.type !== 'schedule') return null;
  return trigger.settings.timezone ?? null;
}

export function capitalize(text: string): string {
  return text.length === 0 ? text : text[0].toUpperCase() + text.slice(1);
}

/** Secondary line for a step: what it actually does, resolved against the catalog.
 *    action → "gmail · Search emails"   (falls back to the raw action name)
 *    ai     → "AI · 2 tools" / "AI"
 *    filter → "Filter · rules" / "Filter · AI" */
export function stepLabel(step: AutomationStep, catalog: Catalog | null): string {
  if (step.type === 'action') {
    const { integration, action } = step.settings;
    const label = findCatalogAction(catalog, integration, action)?.label ?? action;
    return integration ? `${integration} · ${label}` : label;
  }
  if (step.type === 'ai') {
    const count = step.settings.tools?.length ?? 0;
    return count > 0 ? `AI · ${count} ${count === 1 ? 'tool' : 'tools'}` : 'AI';
  }
  return step.settings.mode === 'ai' ? 'Filter · AI' : 'Filter · rules';
}

/** Structural equality, used to decide whether a draft document is dirty. */
export function documentsEqual(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (typeof a !== typeof b || a === null || b === null) return false;
  if (Array.isArray(a) || Array.isArray(b)) {
    if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) return false;
    return a.every((item, i) => documentsEqual(item, b[i]));
  }
  if (typeof a !== 'object') return false;
  const ao = a as Record<string, unknown>;
  const bo = b as Record<string, unknown>;
  const aKeys = Object.keys(ao).filter((k) => ao[k] !== undefined);
  const bKeys = Object.keys(bo).filter((k) => bo[k] !== undefined);
  if (aKeys.length !== bKeys.length) return false;
  return aKeys.every((k) => k in bo && documentsEqual(ao[k], bo[k]));
}
