'use client';

import type { FieldValue } from '@/lib/automations/types';
import { cn } from '@/lib/utils';

export type FieldMode = FieldValue['kind'];

export const MODE_META: Record<FieldMode, { label: string; hint: string }> = {
  literal: { label: 'Value', hint: 'Type the value yourself' },
  ref: { label: 'From step', hint: 'Use a value produced by an earlier step' },
  ai: { label: 'Ask AI', hint: 'Describe it and the AI fills it in when the run happens' },
};

const ALL_MODES: FieldMode[] = ['literal', 'ref', 'ai'];

/** The three-way segmented control every step field carries: Value · From step · Ask AI.
 *  Switching mode is a gesture, so it commits immediately. */
export default function FieldModeToggle({
  mode,
  onChange,
  modes = ALL_MODES,
  label,
}: {
  mode: FieldMode;
  onChange(next: FieldMode): void;
  /** Restrict the offered modes — filter conditions have no "Ask AI" side, for one. */
  modes?: FieldMode[];
  /** Accessible name, e.g. the field label. */
  label: string;
}) {
  return (
    <div
      role="group"
      aria-label={`How to fill ${label}`}
      className="inline-flex items-center gap-0.5 p-0.5 rounded-lg bg-[color:var(--surface-muted)]"
    >
      {modes.map((m) => {
        const active = m === mode;
        return (
          <button
            key={m}
            type="button"
            onClick={() => !active && onChange(m)}
            aria-pressed={active}
            title={MODE_META[m].hint}
            className={cn(
              'px-2 py-[3px] rounded-md text-[10.5px] font-medium transition-colors',
              active
                ? 'bg-white text-[color:var(--foreground)] shadow-[0_1px_2px_rgba(0,0,0,0.06)]'
                : 'text-[color:var(--muted-foreground)] hover:text-[color:var(--foreground)]'
            )}
          >
            {MODE_META[m].label}
          </button>
        );
      })}
    </div>
  );
}
