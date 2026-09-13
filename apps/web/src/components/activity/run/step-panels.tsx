'use client';

import Link from 'next/link';
import { ChevronRight } from 'lucide-react';
import { prettyJson } from '@/lib/automations/format';
import type { RunStep, TraceEntry } from '@/lib/automations/types';
import { errorField, fieldLabel, type StepLane } from './geometry';

const PANEL = 'flex min-w-0 flex-col gap-2 rounded-2xl border border-[color:var(--border)] bg-white px-4 py-3.5';
const CAPTION = 'text-[12px] font-semibold uppercase tracking-[0.08em] text-[color:var(--muted-foreground)]';
const CODE = 'max-h-[280px] overflow-auto whitespace-pre-wrap break-words rounded-[10px] px-3 py-2.5 font-mono text-[11px] leading-[18px]';

/** A step that was tried more than once and got the same answer every time is worth
 *  saying out loud — it is the difference between "flaky" and "wrong". */
function sameEveryTry(step: RunStep): boolean {
  const errors = step.trace
    .filter((entry) => entry.kind === 'attempt')
    .map((entry) => (entry as Extract<TraceEntry, { kind: 'attempt' }>).error ?? '');
  return errors.length > 1 && new Set(errors).size === 1;
}

function isEmpty(value: unknown): boolean {
  if (value === null || value === undefined) return true;
  if (typeof value === 'object') return Object.keys(value as object).length === 0;
  return value === '';
}

/** What the selected step sent and what it got back, side by side. Two halves of one
 *  question — "is this the automation's fault or the tool's?" — so they are never more
 *  than one glance apart. */
export default function StepPanels({
  lane,
  automationId,
}: {
  lane: StepLane;
  automationId: string;
}) {
  const step = lane.step;
  const field = errorField(step);
  const tries = sameEveryTry(step)
    ? 'every try, identical'
    : lane.attempts > 1
      ? `try ${step.attempt}`
      : null;

  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <section className={PANEL}>
          <div className="flex items-center justify-between gap-3">
            <h2 className={CAPTION}>What it sent</h2>
            <span className="truncate text-[11px] text-[color:var(--muted-foreground)]">
              {step.name}
              {tries ? ` · ${tries}` : ''}
            </span>
          </div>
          {isEmpty(step.resolvedInput) ? (
            <p className="text-[12px] leading-[18px] text-[color:var(--muted-foreground)]">
              {lane.ran
                ? 'Nothing — this step takes no inputs of its own.'
                : 'Nothing — the run stopped before this step.'}
            </p>
          ) : (
            <pre className={`${CODE} bg-[#FAFAFC]`}>{prettyJson(step.resolvedInput)}</pre>
          )}
        </section>

        <section className={PANEL}>
          <div className="flex items-center justify-between gap-3">
            <h2 className={CAPTION}>What came back</h2>
            {step.error && tries && (
              <span className="truncate text-[11px] text-[color:var(--muted-foreground)]">
                {tries}
              </span>
            )}
          </div>

          {step.error ? (
            <pre className={`${CODE} bg-[rgba(212,24,61,0.05)] text-[#D4183D]`}>{step.error}</pre>
          ) : isEmpty(step.output) ? (
            <p className="text-[12px] leading-[18px] text-[color:var(--muted-foreground)]">
              {lane.ran ? 'Nothing — this step returned no output.' : 'This step never ran.'}
            </p>
          ) : (
            <pre className={`${CODE} bg-[#FAFAFC]`}>{prettyJson(step.output)}</pre>
          )}

          {field && (
            <div className="mt-0.5 flex flex-wrap items-center gap-2">
              <Link
                href={`/automations/${encodeURIComponent(automationId)}?step=${encodeURIComponent(step.stepId)}`}
                className="inline-flex h-8 shrink-0 items-center rounded-[10px] bg-[color:var(--primary)] px-3 text-[12px] font-medium text-[color:var(--primary-foreground)] transition hover:opacity-90"
              >
                Fix this field
              </Link>
              <span className="text-[11px] text-[color:var(--muted-foreground)]">
                Opens the step with the {fieldLabel(field)} field selected.
              </span>
            </div>
          )}
        </section>
      </div>

      <ToolCalls trace={step.trace} />
    </div>
  );
}

/** The AI step's tool activity, mirrored into the trace as it happened. Same collapsed
 *  cards the editor's run panel uses, so a call looks the same wherever you meet it. */
function ToolCalls({ trace }: { trace: TraceEntry[] }) {
  const calls = trace.filter(
    (entry) => entry.kind === 'tool_call' || entry.kind === 'tool_result'
  );
  if (calls.length === 0) return null;

  return (
    <section className="flex flex-col gap-2 rounded-2xl border border-[color:var(--border)] bg-white px-4 py-3.5">
      <h2 className={CAPTION}>What it did along the way</h2>
      <div className="flex flex-col gap-1">
        {calls.map((entry, i) => {
          if (entry.kind === 'tool_call') {
            const call = entry as Extract<TraceEntry, { kind: 'tool_call' }>;
            return <ToolCard key={i} tool={call.tool} verb="call" body={call.args} ok />;
          }
          const result = entry as Extract<TraceEntry, { kind: 'tool_result' }>;
          return (
            <ToolCard
              key={i}
              tool={result.tool}
              verb="result"
              body={result.result}
              ok={result.ok !== false}
            />
          );
        })}
      </div>
    </section>
  );
}

function ToolCard({
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
    <details className="group rounded-[10px] bg-[#FAFAFC] px-2.5 py-1.5">
      <summary className="flex cursor-pointer list-none items-center gap-2 text-[11px]">
        <ChevronRight
          size={11}
          strokeWidth={2}
          className="shrink-0 text-[color:var(--muted-foreground)] transition-transform group-open:rotate-90"
        />
        <span
          className="h-1 w-1 shrink-0 rounded-full"
          style={{ background: ok ? '#10A37F' : '#D4183D' }}
        />
        <span className="truncate font-mono">{tool}</span>
        <span className="ml-auto shrink-0 text-[10px] text-[color:var(--muted-foreground)]">
          {verb}
        </span>
      </summary>
      <pre className="mt-1.5 max-h-40 overflow-auto whitespace-pre-wrap break-words font-mono text-[10px] leading-[16px] text-[color:var(--muted-foreground)]">
        {body ?? '—'}
      </pre>
    </details>
  );
}
