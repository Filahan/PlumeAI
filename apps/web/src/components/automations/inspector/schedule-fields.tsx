'use client';

import { useMemo, type ReactNode } from 'react';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import LabeledField from './labeled-field';
import { TextField } from './text-field';
import TimezonePicker from './timezone-picker';
import { browserTimezone, parseCronPreset } from './next-runs';

export type Preset = 'hourly' | 'daily' | 'weekdays' | 'weekly' | 'custom';

const DAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const HOURS = Array.from({ length: 24 }, (_, h) => String(h).padStart(2, '0'));
/** Quarter hours. `parseCronPreset` reads any minute, so a hand-written `07 9 * * *`
 *  still displays correctly — it just isn't one of the offered choices. */
const MINUTES = [0, 15, 30, 45];

const PRESET_LABELS: Record<Preset, string> = {
  hourly: 'Every hour',
  daily: 'Every day at…',
  weekdays: 'Weekdays at…',
  weekly: 'Once a week on…',
  custom: 'Custom (cron)',
};

/** Which preset a cron expression came from — `custom` for anything hand-written. */
export function presetOf(cron: string): Preset {
  const shape = parseCronPreset(cron);
  if (!shape) return 'custom';
  if (shape.hour === null) return 'hourly';
  if (shape.dows === null) return 'daily';
  return shape.dows.length === 5 ? 'weekdays' : 'weekly';
}

/** The minute is threaded through rather than pinned to 0: `parseCronPreset` accepts any
 *  minute, so hardcoding it here made the form show 09:00 for `30 9 * * *` and then
 *  silently rewrite the schedule on the next unrelated change. */
export function buildCron(preset: Preset, hour: number, minute: number, day: number): string {
  switch (preset) {
    case 'hourly':
      return `${minute} * * * *`;
    case 'weekdays':
      return `${minute} ${hour} * * 1-5`;
    case 'weekly':
      return `${minute} ${hour} * * ${day}`;
    default:
      return `${minute} ${hour} * * *`;
  }
}

function timeLabel(hour: number, minute: number): string {
  return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`;
}

/** The cron half of the trigger form: a preset, its time, and the timezone it means. */
export default function ScheduleFields({
  cron,
  timezone,
  onChange,
}: {
  cron: string;
  timezone: string;
  onChange(cron: string, timezone: string): void;
}) {
  const fallback = useMemo(() => browserTimezone(), []);
  const timezones = useMemo(() => {
    try {
      return Intl.supportedValuesOf('timeZone');
    } catch {
      return [fallback, 'UTC'];
    }
  }, [fallback]);

  const preset = presetOf(cron);
  const shape = parseCronPreset(cron);
  const hour = shape?.hour ?? 9;
  const minute = shape?.minute ?? 0;
  const day = shape?.dows?.[0] ?? 1;

  const rewrite = (next: Partial<{ preset: Preset; hour: number; minute: number; day: number }>) =>
    onChange(
      buildCron(
        next.preset ?? preset,
        next.hour ?? hour,
        next.minute ?? minute,
        next.day ?? day
      ),
      timezone
    );

  return (
    <div className="space-y-2.5">
      <LabeledField label="How often">
        <Select
          value={preset}
          onValueChange={(next) => {
            if (typeof next !== 'string' || next === 'custom') return;
            rewrite({ preset: next as Preset });
          }}
        >
          <PresetTrigger label="How often">{PRESET_LABELS[preset]}</PresetTrigger>
          <SelectContent className="rounded-xl">
            {(Object.keys(PRESET_LABELS) as Preset[]).map((p) => (
              <SelectItem key={p} value={p} className="text-[13px]" disabled={p === 'custom'}>
                {PRESET_LABELS[p]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </LabeledField>

      {preset === 'weekly' && (
        <LabeledField label="Day">
          <Select
            value={String(day)}
            onValueChange={(next) => {
              if (typeof next === 'string') rewrite({ preset: 'weekly', day: Number(next) });
            }}
          >
            <PresetTrigger label="Day of the week">{DAYS[day] ?? DAYS[1]}</PresetTrigger>
            <SelectContent className="rounded-xl">
              {DAYS.map((name, index) => (
                <SelectItem key={name} value={String(index)} className="text-[13px]">
                  {name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </LabeledField>
      )}

      {preset === 'hourly' && (
        <LabeledField
          label="At minute"
          hint={`Every hour, ${minute} ${minute === 1 ? 'minute' : 'minutes'} past the hour.`}
        >
          <Select
            value={String(minute)}
            onValueChange={(next) => {
              if (typeof next === 'string') rewrite({ minute: Number(next) });
            }}
          >
            <PresetTrigger label="Minutes past the hour">
              {String(minute).padStart(2, '0')}
            </PresetTrigger>
            <SelectContent className="rounded-xl">
              {MINUTES.map((m) => (
                <SelectItem key={m} value={String(m)} className="text-[13px]">
                  {String(m).padStart(2, '0')}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </LabeledField>
      )}

      {preset !== 'hourly' && preset !== 'custom' && (
        <LabeledField label="Time" hint={`Runs at ${timeLabel(hour, minute)}.`}>
          <div className="flex items-center gap-1.5">
            <Select
              value={String(hour)}
              onValueChange={(next) => {
                if (typeof next === 'string') rewrite({ hour: Number(next) });
              }}
            >
              <PresetTrigger label="Hour of the day">
                {HOURS[hour] ?? HOURS[9]}
              </PresetTrigger>
              <SelectContent className="rounded-xl max-h-[240px]">
                {HOURS.map((text, index) => (
                  <SelectItem key={text} value={String(index)} className="text-[13px]">
                    {text}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <span className="shrink-0 text-[13px] text-[color:var(--muted-foreground)]">:</span>
            <Select
              value={String(minute)}
              onValueChange={(next) => {
                if (typeof next === 'string') rewrite({ minute: Number(next) });
              }}
            >
              <PresetTrigger label="Minutes past the hour">
                {String(minute).padStart(2, '0')}
              </PresetTrigger>
              <SelectContent className="rounded-xl">
                {MINUTES.map((m) => (
                  <SelectItem key={m} value={String(m)} className="text-[13px]">
                    {String(m).padStart(2, '0')}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </LabeledField>
      )}

      <LabeledField
        label="Cron expression"
        hint="Five fields: minute, hour, day of month, month, weekday."
      >
        {(controlId) => (
          <TextField
            id={controlId}
            value={cron}
            className="font-mono text-[12px] md:text-[12px]"
            onChange={() => {}}
            onFlush={(text) => {
              const trimmed = text.trim();
              if (trimmed.length > 0 && trimmed !== cron) onChange(trimmed, timezone);
            }}
          />
        )}
      </LabeledField>

      <LabeledField label="Timezone">
        {(controlId) => (
          <TimezonePicker
            id={controlId}
            value={timezone}
            zones={timezones}
            onChange={(next) => onChange(cron, next)}
          />
        )}
      </LabeledField>
    </div>
  );
}

function PresetTrigger({ label, children }: { label: string; children: ReactNode }) {
  return (
    <SelectTrigger
      aria-label={label}
      className="w-full h-8 rounded-lg border-[color:var(--border)] bg-white text-[13px]"
    >
      <SelectValue>{children}</SelectValue>
    </SelectTrigger>
  );
}
