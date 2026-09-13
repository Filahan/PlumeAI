'use client';

import { dayName, shortDay } from './schedule-draft';

/** The seven days, for when none of the quick chips is what you meant.
 *
 *  Toggles rather than a multi-select: the whole week fits on one line, and a set you can
 *  see is easier to trust than a list you have to open. Turning the last day off is
 *  refused — a schedule that fires on no days is not a schedule. */
export default function ScheduleDayPicker({
  dows,
  onChange,
}: {
  /** `null` means every day — every chip reads as on. */
  dows: number[] | null;
  onChange(next: number[]): void;
}) {
  const selected = dows ?? [0, 1, 2, 3, 4, 5, 6];

  return (
    <div className="flex flex-wrap gap-1" role="group" aria-label="Days of the week">
      {[1, 2, 3, 4, 5, 6, 0].map((day) => {
        const on = selected.includes(day);
        return (
          <button
            key={day}
            type="button"
            aria-pressed={on}
            aria-label={dayName(day)}
            onClick={() => {
              const next = on ? selected.filter((d) => d !== day) : [...selected, day];
              if (next.length > 0) onChange(next.sort((a, b) => a - b));
            }}
            className={`flex h-7 w-9 items-center justify-center rounded-lg border text-[11px] font-medium outline-none transition-colors focus-visible:ring-3 focus-visible:ring-[color:var(--ring)]/50 ${
              on
                ? 'border-[color:var(--primary)] bg-[color:var(--primary)] text-white'
                : 'border-[color:var(--border)] bg-white text-[color:var(--muted-foreground)] hover:bg-[color:var(--surface-muted)]'
            }`}
          >
            {shortDay(day)}
          </button>
        );
      })}
    </div>
  );
}
