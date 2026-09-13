'use client';

import { ChevronRight } from 'lucide-react';
import type { AutomationStep, RetryPolicy } from '@/lib/automations/types';
import { TextField } from './text-field';
import { useStepPatch } from './use-step-patch';

/** Mirrors the backend defaults (`app.schemas.documents.RetryPolicy`). */
const DEFAULT_RETRY: RetryPolicy = { max_attempts: 3, backoff_seconds: 10 };

/** Read a number the user has finished typing.
 *
 *  Blank (or nonsense) keeps `fallback` — the value already on the step — rather than
 *  snapping to `min`, which is what the old per-keystroke version did: clearing the box
 *  to retype "5" committed `Number('') === 0` first and the field jumped to 1. */
function commitNumber(text: string, min: number, max: number, fallback: number): number {
  const trimmed = text.trim();
  if (trimmed === '') return fallback;
  const parsed = Number(trimmed);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(max, Math.max(min, Math.round(parsed)));
}

/** Retry and timeout, folded away because most automations never touch them.
 *
 *  Every field here commits on blur/Enter only: these are three small numbers, and a
 *  round trip per keystroke buys nothing but a fight with the caret. */
export default function RetrySettings({ step }: { step: AutomationStep }) {
  const { patchStep } = useStepPatch();
  const retry = step.retry ?? DEFAULT_RETRY;
  const timeout = step.timeout_seconds ?? null;

  const setRetry = (next: RetryPolicy) => patchStep(step.id, { retry: next });

  return (
    <details className="group rounded-xl border border-[color:var(--border)] px-3 py-2">
      <summary className="flex items-center gap-1 cursor-pointer list-none text-[12px] font-medium text-[color:var(--muted-foreground)] hover:text-[color:var(--foreground)]">
        <ChevronRight size={12} strokeWidth={2} className="transition-transform group-open:rotate-90" />
        Advanced
      </summary>

      <div className="mt-2.5 space-y-2.5">
        <Row
          label="Tries before giving up"
          hint="Counting the first attempt."
          value={String(retry.max_attempts)}
          onCommit={(text) => {
            const next = commitNumber(text, 1, 10, retry.max_attempts);
            if (next !== retry.max_attempts) setRetry({ ...retry, max_attempts: next });
          }}
          min={1}
          max={10}
        />
        <Row
          label="Wait between tries"
          hint="Seconds. Doubles after each failure."
          value={String(retry.backoff_seconds)}
          onCommit={(text) => {
            const next = commitNumber(text, 0, 300, retry.backoff_seconds);
            if (next !== retry.backoff_seconds) setRetry({ ...retry, backoff_seconds: next });
          }}
          min={0}
          max={300}
        />
        <Row
          label="Give up after"
          hint="Seconds for one attempt. Empty means no limit."
          value={timeout === null ? '' : String(timeout)}
          onCommit={(text) => {
            // The one field where blank is a real answer, so it clears the timeout
            // instead of keeping what was there.
            const next = text.trim() === '' ? null : commitNumber(text, 1, 3600, timeout ?? 60);
            if (next !== timeout) patchStep(step.id, { timeout_seconds: next });
          }}
          min={1}
          max={3600}
        />
      </div>
    </details>
  );
}

function Row({
  label,
  hint,
  value,
  onCommit,
  min,
  max,
}: {
  label: string;
  hint: string;
  value: string;
  /** Blur or Enter, with whatever text the box holds. */
  onCommit(text: string): void;
  min: number;
  max: number;
}) {
  return (
    <div className="flex items-start gap-2">
      <div className="min-w-0 flex-1">
        <div className="text-[12px] font-medium">{label}</div>
        <p className="text-[11px] text-[color:var(--muted-foreground)]">{hint}</p>
      </div>
      <div className="w-[72px] shrink-0">
        <TextField
          type="number"
          min={min}
          max={max}
          value={value}
          aria-label={label}
          onChange={() => {}}
          onFlush={onCommit}
        />
      </div>
    </div>
  );
}
