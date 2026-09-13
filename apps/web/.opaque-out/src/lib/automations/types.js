"use strict";
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
Object.defineProperty(exports, "__esModule", { value: true });
exports.MCP_SERVER_NAME_RE = exports.MCP_INTEGRATION_PREFIX = exports.BUILTIN_INTEGRATION = exports.ACTIVE_RUN_STATUSES = exports.TERMINAL_RUN_STATUSES = exports.UNARY_CONDITION_OPS = void 0;
exports.isRunActive = isRunActive;
exports.mcpServerOf = mcpServerOf;
exports.findCatalogMcpServer = findCatalogMcpServer;
exports.catalogActions = catalogActions;
exports.findCatalogAction = findCatalogAction;
exports.findCatalogIntegration = findCatalogIntegration;
exports.newStepId = newStepId;
exports.describeTrigger = describeTrigger;
exports.triggerTimezone = triggerTimezone;
exports.capitalize = capitalize;
exports.stepLabel = stepLabel;
exports.documentsEqual = documentsEqual;
/** Ops that take no `right` operand. */
exports.UNARY_CONDITION_OPS = [
    'is_empty',
    'is_not_empty',
    'is_true',
    'is_false',
];
exports.TERMINAL_RUN_STATUSES = ['succeeded', 'failed', 'cancelled'];
exports.ACTIVE_RUN_STATUSES = ['queued', 'running'];
function isRunActive(status) {
    return !!status && exports.ACTIVE_RUN_STATUSES.includes(status);
}
exports.BUILTIN_INTEGRATION = 'builtin';
/** Mirrors `app.mcp.schemas.mcp_integration`: every MCP action's `integration`. */
exports.MCP_INTEGRATION_PREFIX = 'mcp:';
/** `"mcp:notion"` → `"notion"`; `null` for any other integration name. */
function mcpServerOf(integration) {
    return integration.startsWith(exports.MCP_INTEGRATION_PREFIX)
        ? integration.slice(exports.MCP_INTEGRATION_PREFIX.length)
        : null;
}
function findCatalogMcpServer(catalog, name) {
    return catalog?.mcpServers?.find((s) => s.name === name);
}
/** Every action in the catalog, integrations first, then builtins, then MCP tools. */
function catalogActions(catalog) {
    if (!catalog)
        return [];
    return [
        ...catalog.integrations.flatMap((i) => i.actions),
        ...catalog.builtinActions,
        ...(catalog.mcpServers ?? []).flatMap((s) => s.actions),
    ];
}
function findCatalogAction(catalog, integration, action) {
    if (!catalog)
        return undefined;
    if (integration === exports.BUILTIN_INTEGRATION) {
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
function findCatalogIntegration(catalog, name) {
    return catalog?.integrations.find((i) => i.name === name);
}
/** Mirrors `app.mcp.schemas.SERVER_NAME_RE`. The name becomes part of every tool id the
 *  model sees (`mcp__<name>__<tool>`), so it has to stay a slug. */
exports.MCP_SERVER_NAME_RE = /^[a-z0-9][a-z0-9_-]{1,30}$/;
// ─── Helpers ────────────────────────────────────────────────────────────────────────
/** Fresh step id in the backend's format (`^step_[a-z0-9]{5,}$`). */
function newStepId() {
    let suffix = '';
    while (suffix.length < 6) {
        suffix += Math.random().toString(36).slice(2);
    }
    return `step_${suffix.slice(0, 6)}`;
}
function cronTime(minute, hour) {
    if (!/^\d+$/.test(minute) || !/^\d+$/.test(hour))
        return null;
    return `${String(Number(hour)).padStart(2, '0')}:${String(Number(minute)).padStart(2, '0')}`;
}
/** A short, lowercase phrase describing a trigger — a verbatim mirror of the backend's
 *  `app.services.documents.diff.describe_trigger`, which is also what feeds
 *  `AutomationSummary.triggerSummary`. Capitalize at the call site for standalone use;
 *  the timezone is deliberately NOT part of the phrase (see `triggerTimezone`). */
function describeTrigger(trigger) {
    if (!trigger || trigger.type === 'manual')
        return 'manual trigger';
    const settings = trigger.settings;
    if (settings.mode === 'interval') {
        const n = settings.every_minutes;
        return `every ${n} ${n === 1 ? 'minute' : 'minutes'}`;
    }
    const cron = settings.cron ?? '';
    const parts = cron.split(' ').filter((p) => p.length > 0);
    if (parts.length !== 5)
        return `cron schedule '${cron}'`;
    const [minute, hour, dom, month, dow] = parts;
    const time = cronTime(minute, hour);
    if (time && dom === '*' && month === '*' && dow === '1-5')
        return `weekdays at ${time}`;
    if (time && dom === '*' && month === '*' && dow === '*')
        return `daily at ${time}`;
    return `cron schedule '${cron}'`;
}
/** The trigger's timezone, when it has one — rendered next to `describeTrigger` rather
 *  than inside it, so the phrase stays identical to the server's `triggerSummary`. */
function triggerTimezone(trigger) {
    if (!trigger || trigger.type !== 'schedule')
        return null;
    return trigger.settings.timezone ?? null;
}
function capitalize(text) {
    return text.length === 0 ? text : text[0].toUpperCase() + text.slice(1);
}
/** Secondary line for a step: what it actually does, resolved against the catalog.
 *    action → "gmail · Search emails"   (falls back to the raw action name)
 *    ai     → "AI · 2 tools" / "AI"
 *    filter → "Filter · rules" / "Filter · AI" */
function stepLabel(step, catalog) {
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
function documentsEqual(a, b) {
    if (a === b)
        return true;
    if (typeof a !== typeof b || a === null || b === null)
        return false;
    if (Array.isArray(a) || Array.isArray(b)) {
        if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length)
            return false;
        return a.every((item, i) => documentsEqual(item, b[i]));
    }
    if (typeof a !== 'object')
        return false;
    const ao = a;
    const bo = b;
    const aKeys = Object.keys(ao).filter((k) => ao[k] !== undefined);
    const bKeys = Object.keys(bo).filter((k) => bo[k] !== undefined);
    if (aKeys.length !== bKeys.length)
        return false;
    return aKeys.every((k) => k in bo && documentsEqual(ao[k], bo[k]));
}
