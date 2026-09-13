'use client';

import { useState } from 'react';
import ScheduleDayPicker from './schedule-day-picker';
import SchedulePill, { type PillOption } from './schedule-pill';
import {
  clockLabel,
  dayName,
  daysPhrase,
  dowField,
  parseDowField,
  type ScheduleDraft,
} from './schedule-draft';

/** Half-hours. Any other time survives a round trip — it is simply added to the list. */
const TIMES: PillOption[] = Array.from({ length: 48 }, (_, i) => {
  const label = clockLabel(Math.floor(i / 2), (i % 2) * 30);
  return { value: label, label };
});

const MINUTES: PillOption[] = [1, 2, 5, 10, 15, 30, 60, 120, 360, 720, 1440].map((n) => ({
  value: String(n),
  label: String(n),
}));

const DAY_OPTIONS: PillOption[] = [
  { value: '*', label: 'day' },
  { value: '1-5', label: 'weekday' },
  { value: '0,6', label: 'weekend day' },
  ...[1, 2, 3, 4, 5, 6, 0].map((d) => ({ value: String(d), label: dayName(d) })),
];

const CHIPS: { label: string; field: string }[] = [
  { label: 'Every day', field: '*' },
  { label: 'Weekdays', field: '1-5' },
  { label: 'Mondays', field: '1' },
];

/** The schedule as a sentence you edit word by word.
 *
 *  Every control writes straight into the draft — there is no separate "apply", because
 *  the preview underneath is the feedback. */
export default function ScheduleSentence({
  draft,
  timezones,
  onChange,
}: {
  draft: ScheduleDraft;
  timezones: string[];
  onChange(patch: Partial<ScheduleDraft>): void;
}) {
  const field = dowField(draft.dows);
  const [picking, setPicking] = useState(() => !CHIPS.some((chip) => chip.field === field));

  const time = clockLabel(draft.hour, draft.minute);
  const times = TIMES.some((option) => option.value === time)
    ? TIMES
    : [{ value: time, label: time }, ...TIMES];
  const dayOptions = DAY_OPTIONS.some((option) => option.value === field)
    ? DAY_OPTIONS
    : [{ value: field, label: daysPhrase(draft.dows) }, ...DAY_OPTIONS];
  const zones = timezones.includes(draft.timezone)
    ? timezones
    : [draft.timezone, ...timezones];

  return (
    <div className="flex flex-col gap-3 rounded-2xl border border-[color:var(--border)] bg-[#FAFAFC] p-4">
      <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-[color:var(--muted-foreground)]">
        Run it
      </div>

      {draft.mode === 'interval' ? (
        <div className="flex flex-wrap items-center gap-2 text-[15px] leading-8">
          <span>every</span>
          <SchedulePill
            label="Minutes between runs"
            value={String(Math.round(draft.everyMinutes))}
            options={MINUTES}
            numeric
            onChange={(next) => onChange({ everyMinutes: Number(next) })}
          />
          <span>minutes</span>
        </div>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2 text-[15px] leading-8">
            <span>every</span>
            <SchedulePill
              label="Days"
              value={field}
              options={dayOptions}
              onChange={(next) => {
                setPicking(false);
                onChange({ dows: parseDowField(next) });
              }}
            />
            <span>at</span>
            <SchedulePill
              label="Time"
              value={time}
              options={times}
              numeric
              onChange={(next) => {
                const [hour, minute] = next.split(':').map(Number);
                onChange({ hour, minute });
              }}
            />
            <span>in</span>
            <SchedulePill
              label="Timezone"
              value={draft.timezone}
              options={zones.map((zone) => ({ value: zone, label: zone }))}
              wide
              onChange={(next) => onChange({ timezone: next })}
            />
          </div>

          <div className="flex flex-wrap gap-1.5">
            {CHIPS.map((chip) => {
              const active = !picking && chip.field === field;
              return (
                <button
                  key={chip.field}
                  type="button"
                  aria-pressed={active}
                  onClick={() => {
                    setPicking(false);
                    onChange({ dows: parseDowField(chip.field) });
                  }}
                  className={`flex h-7 items-center rounded-full border px-2.5 text-[12px] outline-none transition-colors focus-visible:ring-3 focus-visible:ring-[color:var(--ring)]/50 ${
                    active
                      ? 'border-[color:var(--primary)] bg-[color:var(--primary)] font-medium text-white'
                      : 'border-[color:var(--border)] bg-white text-[color:var(--muted-foreground)] hover:text-[color:var(--foreground)]'
                  }`}
                >
                  {chip.label}
                </button>
              );
            })}
            <button
              type="button"
              aria-pressed={picking}
              onClick={() => setPicking((open) => !open)}
              className={`flex h-7 items-center rounded-full border px-2.5 text-[12px] outline-none transition-colors focus-visible:ring-3 focus-visible:ring-[color:var(--ring)]/50 ${
                picking
                  ? 'border-[color:var(--primary)] bg-[color:var(--primary)] font-medium text-white'
                  : 'border-[color:var(--border)] bg-white text-[color:var(--muted-foreground)] hover:text-[color:var(--foreground)]'
              }`}
            >
              Pick days…
            </button>
          </div>

          {picking && (
            <ScheduleDayPicker dows={draft.dows} onChange={(next) => onChange({ dows: next })} />
          )}
        </>
      )}
    </div>
  );
}
