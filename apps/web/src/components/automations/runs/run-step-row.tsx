'use client';

import { AlertCircle, ChevronRight } from 'lucide-react';
import type { RunStep, TraceEntry } from '@/lib/automations/types';
import { formatDuration, prettyJson, statusDot } from '@/lib/automations/format';

/** One step of the active run: status, name, attempt, duration, error, plus collapsible
 *  resolved input / output / trace. Live-updated by the store's run stream. */
export default function RunStepRow({ step }: { step: RunStep }) {
  const hasDetails =
    step.resolvedInput !== null ||
    (step.output !== null && step.output !== undefined) ||
    step.trace.length > 0;

  return (
    <details className="group rounded-xl border border-[color:var(--border)] bg-white px-3 py-2">
      <summary className="flex items-center gap-2 cursor-pointer list-none text-[12px]">
        <ChevronRight
          size={12}
          strokeWidth={2}
          className={`shrink-0 text-[color:var(--muted-foreground)] transition-transform group-open:rotate-90 ${
            hasDetails ? '' : 'opacity-0'
          }`}
        />
        <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${statusDot(step.status)}`} />
        <span className="font-medium truncate">{step.name}</span>
        <span className="text-[10px] uppercase tracking-[0.06em] text-[color:var(--muted-foreground)] shrink-0">
          {step.type}
        </span>
        {step.attempt > 1 && (
          <span className="text-[10px] text-[color:var(--muted-foreground)] shrink-0">
            attempt {step.attempt}
          </span>
        )}
        <span className="ml-auto shrink-0 text-[11px] text-[color:var(--muted-foreground)] tabular-nums">
          {step.durationMs != null ? formatDuration(step.durationMs) : step.status}
        </span>
      </summary>

      <div className="mt-2 space-y-2 pl-[22px]">
        {step.error && (
          <p className="flex items-start gap-1.5 text-[11px] text-[#D4183D]">
            <AlertCircle size={12} strokeWidth={2} className="mt-0.5 shrink-0" />
            <span className="break-words">{step.error}</span>
          </p>
        )}

        {step.resolvedInput !== null && (
          <JsonBlock label="Resolved input" value={step.resolvedInput} />
        )}
        {step.output !== null && step.output !== undefined && (
          <JsonBlock label="Output" value={step.output} />
        )}
        {step.trace.length > 0 && <Trace entries={step.trace} />}
      </div>
    </details>
  );
}

function JsonBlock({ label, value }: { label: string; value: unknown }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-[0.06em] text-[color:var(--muted-foreground)] mb-1">
        {label}
      </div>
      <pre className="text-[11px] font-mono whitespace-pre-wrap break-words rounded-lg bg-[color:var(--surface-muted)] p-2 max-h-48 overflow-y-auto">
        {prettyJson(value)}
      </pre>
    </div>
  );
}

/** Retry attempts and the AI step's tool calls, in the order they happened. Tool calls
 *  collapse the same way the chat's ToolCard does. */
function Trace({ entries }: { entries: TraceEntry[] }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-[0.06em] text-[color:var(--muted-foreground)] mb-1">
        Trace
      </div>
      <div className="space-y-1">
        {entries.map((entry, i) => {
          if (entry.kind === 'attempt') {
            const e = entry as Extract<TraceEntry, { kind: 'attempt' }>;
            return (
              <p key={i} className="text-[11px] text-[#b45309]">
                attempt {e.n} failed{e.error ? `: ${e.error}` : ''}
                {e.retryInSeconds != null && ` — retrying in ${e.retryInSeconds}s`}
              </p>
            );
          }
          if (entry.kind === 'tool_call') {
            const e = entry as Extract<TraceEntry, { kind: 'tool_call' }>;
            return <ToolEntry key={i} tool={e.tool} verb="call" body={e.args} ok />;
          }
          if (entry.kind === 'tool_result') {
            const e = entry as Extract<TraceEntry, { kind: 'tool_result' }>;
            return (
              <ToolEntry key={i} tool={e.tool} verb="result" body={e.result} ok={e.ok !== false} />
            );
          }
          return (
            <pre
              key={i}
              className="text-[10px] font-mono whitespace-pre-wrap break-words text-[color:var(--muted-foreground)]"
            >
              {prettyJson(entry)}
            </pre>
          );
        })}
      </div>
    </div>
  );
}

/** One tool call or its result, collapsed like the chat's ToolCard. */
function ToolEntry({
  tool,
  verb,
  body,
  ok,
}: {
  tool: string;
  verb: 'call' | 'result';
  body?: string;
  ok: boolean;
}) {
  return (
    <details className="rounded-md bg-[color:var(--surface-muted)] px-2 py-1">
      <summary className="flex items-center gap-1.5 cursor-pointer list-none text-[11px]">
        <span className={`w-1 h-1 rounded-full shrink-0 ${ok ? 'bg-[#10A37F]' : 'bg-[#D4183D]'}`} />
        <span className="font-mono truncate">{tool}</span>
        <span className="ml-auto text-[10px] text-[color:var(--muted-foreground)]">{verb}</span>
      </summary>
      <pre className="mt-1 text-[10px] font-mono whitespace-pre-wrap break-words text-[color:var(--muted-foreground)] max-h-40 overflow-y-auto">
        {body ?? '—'}
      </pre>
    </details>
  );
}
