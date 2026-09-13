'use client';

import { AlertTriangle, Loader2 } from 'lucide-react';
import { useCatalog } from '@/lib/automations/store';
import {
  BUILTIN_INTEGRATION,
  findCatalogAction,
  findCatalogIntegration,
  findCatalogMcpServer,
  mcpServerOf,
  type ActionStep,
} from '@/lib/automations/types';
import { prettyJson } from '@/lib/automations/format';
import ConnectionBanner from './connection-banner';
import McpServerBanner from './mcp-server-banner';
import RetrySettings from './retry-settings';
import SchemaForm from './schema-form/schema-form';

/** Settings for an `action` step: what the tool does, whether it can run, and a form
 *  generated from its `inputSchema`. */
export default function ActionForm({ step }: { step: ActionStep }) {
  const catalog = useCatalog();
  const { integration: integrationName, action: actionName } = step.settings;
  const action = findCatalogAction(catalog, integrationName, actionName);
  const integration = findCatalogIntegration(catalog, integrationName);

  // An MCP server that is off or broken publishes no actions at all, so it has to be
  // recognised before the missing-action path — otherwise turning a server off turns
  // every step that uses it into "this action no longer exists".
  const mcpName = mcpServerOf(integrationName);
  const mcpServer = mcpName === null ? undefined : findCatalogMcpServer(catalog, mcpName);
  const mcpUnusable = mcpServer !== undefined && (!mcpServer.enabled || !!mcpServer.lastError);

  if (catalog === null) {
    return (
      <p className="flex items-center gap-1.5 text-[12px] text-[color:var(--muted-foreground)]">
        <Loader2 size={12} className="animate-spin" /> Loading this action…
      </p>
    );
  }

  if (!action && mcpUnusable && mcpServer) {
    return (
      <div className="space-y-3">
        <McpServerBanner server={mcpServer} />
        <pre className="text-[11px] font-mono whitespace-pre-wrap break-words rounded-lg bg-[color:var(--surface-muted)] p-2.5">
          {prettyJson(step.settings)}
        </pre>
      </div>
    );
  }

  if (!action) {
    return (
      <div className="space-y-3">
        <div className="rounded-xl border border-[#D4183D]/30 bg-[#D4183D]/5 px-3 py-2.5">
          <p className="flex items-start gap-1.5 text-[12px] font-medium text-[#D4183D]">
            <AlertTriangle size={13} strokeWidth={2} className="mt-0.5 shrink-0" />
            <span>
              This step uses an action that no longer exists:{' '}
              <code className="font-mono text-[11px]">
                {integrationName}.{actionName}
              </code>
            </span>
          </p>
          <p className="mt-1 text-[11px] text-[#D4183D]/80">
            Delete the step, or fix it in the JSON view. Its current settings are below.
          </p>
        </div>
        <pre className="text-[11px] font-mono whitespace-pre-wrap break-words rounded-lg bg-[color:var(--surface-muted)] p-2.5">
          {prettyJson(step.settings)}
        </pre>
      </div>
    );
  }

  const disconnected =
    integrationName !== BUILTIN_INTEGRATION && integration !== undefined && !integration.connected;

  return (
    <div className="space-y-3">
      <div className="rounded-xl border border-[color:var(--border)] px-3 py-2.5">
        <div className="flex items-baseline gap-1.5">
          <span className="text-[12px] font-medium truncate">{action.label}</span>
          <span className="text-[10px] uppercase tracking-[0.06em] text-[color:var(--muted-foreground)] shrink-0">
            {integrationName}
          </span>
        </div>
        {action.description && (
          <p className="mt-0.5 text-[11px] leading-snug text-[color:var(--muted-foreground)]">
            {action.description}
          </p>
        )}
        {action.outputDescription && (
          <p className="mt-1 text-[11px] leading-snug text-[color:var(--muted-foreground)]">
            <span className="font-medium">Gives back:</span> {action.outputDescription}
          </p>
        )}
      </div>

      {mcpUnusable && mcpServer && <McpServerBanner server={mcpServer} />}

      {disconnected && integration && <ConnectionBanner integration={integration} />}

      <SchemaForm step={step} schema={action.inputSchema} />

      <RetrySettings step={step} />
    </div>
  );
}
