'use client';

import { CalendarDays, Play, RotateCw } from 'lucide-react';
import type { DraftMode } from './schedule-draft';

const MODES: { id: DraftMode; title: string; hint: string; icon: typeof Play }[] = [
  { id: 'manual', title: 'By hand', hint: 'Only when you press Run', icon: Play },
  { id: 'interval', title: 'On repeat', hint: 'Every few minutes or hours', icon: RotateCw },
  { id: 'cron', title: 'On a calendar', hint: 'Certain days, at a time', icon: CalendarDays },
];

/** The three ways an automation can start. One is always chosen, so they are a group of
 *  pressed-state buttons rather than a list of toggles. */
export default function ScheduleModeCards({
  mode,
  onChange,
}: {
  mode: DraftMode;
  onChange(next: DraftMode): void;
}) {
  return (
    <div className="grid grid-cols-3 gap-2">
      {MODES.map((option) => {
        const Icon = option.icon;
        const active = option.id === mode;
        return (
          <button
            key={option.id}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(option.id)}
            className={`flex flex-col gap-1 rounded-[14px] border-[1.5px] bg-white p-3 text-left outline-none transition-colors focus-visible:ring-3 focus-visible:ring-[color:var(--ring)]/50 ${
              active
                ? 'border-[color:var(--primary)]'
                : 'border-[color:var(--border)] hover:bg-[color:var(--surface-muted)]'
            }`}
          >
            <Icon
              size={16}
              strokeWidth={1.75}
              aria-hidden
              className={
                active ? 'text-[color:var(--primary)]' : 'text-[color:var(--muted-foreground)]'
              }
            />
            <span className="text-[13px] font-medium">{option.title}</span>
            <span className="text-[11px] leading-[15px] text-[color:var(--muted-foreground)]">
              {option.hint}
            </span>
          </button>
        );
      })}
    </div>
  );
}
