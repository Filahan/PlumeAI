'use client';

import { ChevronRight } from 'lucide-react';
import type { AutomationStep, RetryPolicy } from '@/lib/automations/types';
import { TextField } from './text-field';
import { useStepPatch } from './use-step-patch';

/** Mirrors the backend defaults (`app.schemas.documents.RetryPolicy`). */
const DEFAULT_RETRY: RetryPolicy = { max_attempts: 3, backoff_seconds: 10 };

function clamp(text: string, min: number, max: number, fallback: number): number {
  const parsed = Number(text.trim());
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(max, Math.max(min, Math.round(parsed)));
}

/** Retry and timeout, folded away because most automations never touch them. */
export default function RetrySettings({ step }: { step: AutomationStep }) {
  const { patchStepDebounced, flushStep } = useStepPatch();
  const retry = step.retry ?? DEFAULT_RETRY;
  const timeout = step.timeout_seconds ?? null;

  const setRetry = (next: RetryPolicy) =>
    patchStepDebounced(step.id, 'retry', { retry: next });

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
          onChange={(text) =>
            setRetry({ ...retry, max_attempts: clamp(text, 1, 10, DEFAULT_RETRY.max_attempts) })
          }
          onFlush={() => flushStep(step.id, 'retry')}
          min={1}
          max={10}
        />
        <Row
          label="Wait between tries"
          hint="Seconds. Doubles after each failure."
          value={String(retry.backoff_seconds)}
          onChange={(text) =>
            setRetry({
              ...retry,
              backoff_seconds: clamp(text, 0, 300, DEFAULT_RETRY.backoff_seconds),
            })
          }
          onFlush={() => flushStep(step.id, 'retry')}
          min={0}
          max={300}
        />
        <Row
          label="Give up after"
          hint="Seconds for one attempt. Empty means no limit."
          value={timeout === null ? '' : String(timeout)}
          onChange={(text) =>
            patchStepDebounced(step.id, 'timeout_seconds', {
              timeout_seconds: text.trim() === '' ? null : clamp(text, 1, 3600, 60),
            })
          }
          onFlush={() => flushStep(step.id, 'timeout_seconds')}
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
  onChange,
  onFlush,
  min,
  max,
}: {
  label: string;
  hint: string;
  value: string;
  onChange(text: string): void;
  onFlush(): void;
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
          onChange={onChange}
          onFlush={() => onFlush()}
        />
      </div>
    </div>
  );
}
