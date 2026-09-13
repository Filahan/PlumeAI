'use client';

import { useState } from 'react';
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
 *  Switching mode is a gesture, so it commits immediately.
 *
 *  A mode can be *unavailable* rather than merely unset — "Ask AI" on a field holding an
 *  opaque identifier the model could only invent. Such a segment stays rendered and
 *  readable (hiding it would leave the user wondering where the mode went) but is
 *  `aria-disabled`, out of the tab order, and says why when clicked. The mode currently
 *  selected is never disabled: an existing document that already uses it keeps working,
 *  and the caller shows the reason next to the input instead. */
export default function FieldModeToggle({
  mode,
  onChange,
  modes = ALL_MODES,
  label,
  unavailable,
}: {
  mode: FieldMode;
  onChange(next: FieldMode): void;
  /** Restrict the offered modes — filter conditions have no "Ask AI" side, for one. */
  modes?: FieldMode[];
  /** Accessible name, e.g. the field label. */
  label: string;
  /** Modes that cannot be chosen here, each with the sentence explaining why. */
  unavailable?: Partial<Record<FieldMode, string>>;
}) {
  const [blocked, setBlocked] = useState<string | null>(null);
  // The explanation stops applying the moment the mode becomes available again (an
  // earlier step that can supply the value was added), so re-read it rather than trust it.
  const showBlocked =
    blocked !== null && Object.values(unavailable ?? {}).includes(blocked) ? blocked : null;

  return (
    <div className="space-y-1">
      <div
        role="group"
        aria-label={`How to fill ${label}`}
        className="inline-flex items-center gap-0.5 p-0.5 rounded-lg bg-[color:var(--surface-muted)]"
      >
        {modes.map((m) => {
          const active = m === mode;
          // Never disable what is already selected — see the note above.
          const reason = active ? undefined : unavailable?.[m];
          const off = reason !== undefined;
          return (
            <button
              key={m}
              type="button"
              onClick={() => {
                if (off) {
                  setBlocked(reason);
                  return;
                }
                setBlocked(null);
                if (!active) onChange(m);
              }}
              aria-pressed={active}
              aria-disabled={off || undefined}
              tabIndex={off ? -1 : undefined}
              title={reason ?? MODE_META[m].hint}
              className={cn(
                'px-2 py-[3px] rounded-md text-[10.5px] font-medium transition-colors',
                active &&
                  'bg-white text-[color:var(--foreground)] shadow-[0_1px_2px_rgba(0,0,0,0.06)]',
                !active && off && 'text-[color:var(--muted-foreground)]/45 cursor-not-allowed',
                !active &&
                  !off &&
                  'text-[color:var(--muted-foreground)] hover:text-[color:var(--foreground)]'
              )}
            >
              {MODE_META[m].label}
            </button>
          );
        })}
      </div>

      {showBlocked !== null && (
        <p className="text-[11px] leading-snug text-[color:var(--muted-foreground)]">
          {showBlocked}
        </p>
      )}
    </div>
  );
}
