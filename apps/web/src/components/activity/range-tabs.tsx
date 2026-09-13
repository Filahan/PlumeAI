'use client';

import { ACTIVITY_RANGES, type ActivityRange } from '@/lib/activity/derive';

/** How far back the Runs tab looks: Today / 7 days / 30 days.
 *
 *  A pressed-button group rather than a tab list — these filter the page below, they do
 *  not navigate anywhere, so `aria-pressed` is the honest state. */
export default function RangeTabs({
  value,
  onChange,
}: {
  value: ActivityRange;
  onChange: (range: ActivityRange) => void;
}) {
  return (
    <div className="flex shrink-0 items-center gap-1 rounded-[10px] border border-[color:var(--border)] bg-white p-[3px]">
      {ACTIVITY_RANGES.map((range) => {
        const active = range.id === value;
        return (
          <button
            key={range.id}
            type="button"
            onClick={() => onChange(range.id)}
            aria-pressed={active}
            className={`flex h-[26px] items-center rounded-lg px-3 text-[12px] font-medium transition-colors ${
              active
                ? 'bg-[color:var(--primary)] text-white'
                : 'text-[color:var(--muted-foreground)] hover:text-[color:var(--foreground)]'
            }`}
          >
            {range.label}
          </button>
        );
      })}
    </div>
  );
}
