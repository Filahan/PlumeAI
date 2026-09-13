'use client';

import type { ReactNode } from 'react';
import { statusDot } from '@/lib/automations/format';
import type { RunStepStatus } from '@/lib/automations/types';

/** The shared chrome of every canvas node: one card, one sentence.
 *
 *  A node is a plain statement — a title (what the user called it) over a subtitle
 *  (what it actually does) — with only two pieces of state on the right: whether it
 *  needs attention, and how it is doing in the run being watched.
 *
 *  It is a real `<button>` rather than a click-handled div: selecting a step is the
 *  canvas's primary action, and it should work from the keyboard without React Flow's
 *  node focus ring getting involved. */
export default function NodeCard({
  icon,
  index,
  title,
  subtitle,
  selected,
  onSelect,
  needsAttention = false,
  runStatus = null,
  dashed = false,
  highlight = false,
}: {
  icon: ReactNode;
  /** 1-based badge; omitted for the trigger. */
  index?: number;
  title: string;
  subtitle: string;
  selected: boolean;
  onSelect: () => void;
  needsAttention?: boolean;
  runStatus?: RunStepStatus | null;
  dashed?: boolean;
  /** Just changed by the assistant — ringed for a couple of seconds. */
  highlight?: boolean;
}) {
  const skipped = runStatus === 'skipped';

  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={`h-full w-full overflow-hidden rounded-2xl bg-white px-3.5 flex items-center gap-3 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--ring)] ${
        dashed ? 'border border-dashed' : 'border'
      } ${
        selected
          ? 'border-[color:var(--primary)] ring-2 ring-[color:var(--primary)]'
          : highlight
            ? 'border-[color:var(--primary)]/40 ring-2 ring-[color:var(--primary)]/25'
            : 'border-[color:var(--border)] hover:bg-[color:var(--surface-muted)]/60'
      }`}
    >
      {icon}

      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-1.5">
          {index !== undefined && (
            <span className="shrink-0 w-4 h-4 rounded-[5px] bg-[color:var(--surface-muted)] text-[9px] font-semibold inline-flex items-center justify-center tabular-nums text-[color:var(--muted-foreground)]">
              {index}
            </span>
          )}
          <span
            className={`truncate text-[14px] font-medium ${
              skipped ? 'line-through text-[color:var(--muted-foreground)]' : ''
            }`}
          >
            {title}
          </span>
        </span>
        <span className="block truncate text-[12px] text-[color:var(--muted-foreground)]">
          {subtitle}
        </span>
      </span>

      <span className="shrink-0 flex items-center gap-1.5">
        {needsAttention && (
          <span
            className="w-2 h-2 rounded-full bg-[#D4183D]"
            title="Needs attention — open this step to fix it"
            aria-label="Needs attention"
          />
        )}
        {runStatus && (
          <span
            className={`w-2 h-2 rounded-full ${statusDot(runStatus)}`}
            title={`Last run: ${runStatus}`}
            aria-label={`Run status: ${runStatus}`}
          />
        )}
      </span>
    </button>
  );
}
