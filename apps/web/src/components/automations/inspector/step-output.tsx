'use client';

import { useState } from 'react';
import { CheckCheck, Copy } from 'lucide-react';
import { useAutomationsStore, useCurrentAutomation } from '@/lib/automations/store';
import { formatDuration, prettyJson, relativePast, statusDot } from '@/lib/automations/format';

/** The Output tab: what this step produced the last time the automation ran.
 *
 *  Reads the run the store already has selected (`open()` picks the newest run), and
 *  offers to load it when a run exists but hasn't been fetched yet. */
export default function StepOutput({ stepId }: { stepId: string }) {
  const current = useCurrentAutomation();
  const selectRun = useAutomationsStore((s) => s.selectRun);
  const [copied, setCopied] = useState(false);

  if (!current) return null;

  const run = current.activeRun;
  const latest = current.runs[0] ?? null;

  if (!run) {
    return (
      <div className="space-y-2">
        <p className="text-[12px] text-[color:var(--muted-foreground)]">
          {latest ? 'The last run has not been loaded yet.' : 'No run yet.'}
        </p>
        {latest && (
          <button
            type="button"
            onClick={() => void selectRun(latest.id)}
            className="h-7 px-2.5 rounded-lg border border-[color:var(--border)] bg-white text-[11px] font-medium hover:bg-[color:var(--surface-muted)] transition"
          >
            Load the last run
          </button>
        )}
      </div>
    );
  }

  const step = run.steps.find((s) => s.stepId === stepId);
  if (!step) {
    return (
      <p className="text-[12px] text-[color:var(--muted-foreground)]">
        This step did not run{run.startedAt ? ` in the run from ${relativePast(run.startedAt)}` : ''}.
      </p>
    );
  }

  const text = prettyJson(step.output ?? null);

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-1.5 text-[11px] text-[color:var(--muted-foreground)]">
        <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${statusDot(step.status)}`} />
        <span>{step.status}</span>
        {step.durationMs != null && <span className="tabular-nums">· {formatDuration(step.durationMs)}</span>}
        {run.startedAt != null && <span>· {relativePast(run.startedAt)}</span>}
        <button
          type="button"
          onClick={() => {
            void navigator.clipboard?.writeText(text).then(() => {
              setCopied(true);
              setTimeout(() => setCopied(false), 1500);
            });
          }}
          className="ml-auto inline-flex items-center gap-1 hover:text-[color:var(--foreground)]"
        >
          {copied ? <CheckCheck size={11} strokeWidth={2} /> : <Copy size={11} strokeWidth={2} />}
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>

      {step.error && <p className="text-[11px] text-[#D4183D] break-words">{step.error}</p>}

      {step.output === null || step.output === undefined ? (
        <p className="text-[12px] text-[color:var(--muted-foreground)]">
          This step produced nothing.
        </p>
      ) : (
        <pre className="text-[11px] font-mono whitespace-pre-wrap break-words rounded-lg bg-[color:var(--surface-muted)] p-2.5 max-h-[360px] overflow-y-auto">
          {text}
        </pre>
      )}
    </div>
  );
}
