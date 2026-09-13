'use client';

import { AlertCircle } from 'lucide-react';
import type { RunStep } from '@/lib/automations/types';
import { failureHeadline } from './geometry';

/** Why the run stopped, in two lines: the step, named the way the user named it, and
 *  underneath it the exact words the tool came back with. */
export default function RunErrorCard({
  step,
  error,
}: {
  /** The step the run stopped on, when it is known. */
  step: RunStep | null;
  /** The run's own error text. */
  error: string | null;
}) {
  const detail = error ?? step?.error ?? null;

  return (
    <section className="flex items-start gap-3 rounded-[14px] border border-[rgba(212,24,61,0.30)] bg-[rgba(212,24,61,0.05)] px-4 py-3">
      <AlertCircle size={16} strokeWidth={2} className="mt-px shrink-0 text-[#D4183D]" />
      <div className="flex min-w-0 flex-col gap-0.5">
        <p className="text-[13px] font-medium leading-[18px] text-[#D4183D]">
          {failureHeadline(step)}
        </p>
        {detail && (
          <p className="break-words text-[12px] leading-[17px] text-[color:var(--muted-foreground)]">
            {detail}
          </p>
        )}
      </div>
    </section>
  );
}
