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
import { browserTimezone, parseCronPreset } from './next-runs';

export type Preset = 'hourly' | 'daily' | 'weekdays' | 'weekly' | 'custom';

const DAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const HOURS = Array.from({ length: 24 }, (_, h) => `${String(h).padStart(2, '0')}:00`);

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

export function buildCron(preset: Preset, hour: number, day: number): string {
  switch (preset) {
    case 'hourly':
      return '0 * * * *';
    case 'weekdays':
      return `0 ${hour} * * 1-5`;
    case 'weekly':
      return `0 ${hour} * * ${day}`;
    default:
      return `0 ${hour} * * *`;
  }
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
  const day = shape?.dows?.[0] ?? 1;

  return (
    <div className="space-y-2.5">
      <LabeledField label="How often">
        <Select
          value={preset}
          onValueChange={(next) => {
            if (typeof next !== 'string' || next === 'custom') return;
            onChange(buildCron(next as Preset, hour, day), timezone);
          }}
        >
          <Trigger label="How often">{PRESET_LABELS[preset]}</Trigger>
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
              if (typeof next === 'string') onChange(buildCron('weekly', hour, Number(next)), timezone);
            }}
          >
            <Trigger label="Day of the week">{DAYS[day] ?? DAYS[1]}</Trigger>
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

      {preset !== 'hourly' && preset !== 'custom' && (
        <LabeledField label="Time">
          <Select
            value={String(hour)}
            onValueChange={(next) => {
              if (typeof next === 'string') onChange(buildCron(preset, Number(next), day), timezone);
            }}
          >
            <Trigger label="Time of day">{HOURS[hour] ?? '09:00'}</Trigger>
            <SelectContent className="rounded-xl max-h-[240px]">
              {HOURS.map((text, index) => (
                <SelectItem key={text} value={String(index)} className="text-[13px]">
                  {text}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </LabeledField>
      )}

      <LabeledField
        label="Cron expression"
        hint="Five fields: minute, hour, day of month, month, weekday."
      >
        <TextField
          value={cron}
          aria-label="Cron expression"
          className="font-mono text-[12px] md:text-[12px]"
          onChange={() => {}}
          onFlush={(text) => {
            const trimmed = text.trim();
            if (trimmed.length > 0 && trimmed !== cron) onChange(trimmed, timezone);
          }}
        />
      </LabeledField>

      <LabeledField label="Timezone">
        <Select
          value={timezone}
          onValueChange={(next) => {
            if (typeof next === 'string') onChange(cron, next);
          }}
        >
          <Trigger label="Timezone">{timezone}</Trigger>
          <SelectContent className="rounded-xl max-h-[240px]">
            {timezones.map((zone) => (
              <SelectItem key={zone} value={zone} className="text-[13px]">
                {zone}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </LabeledField>
    </div>
  );
}

function Trigger({ label, children }: { label: string; children: ReactNode }) {
  return (
    <SelectTrigger
      aria-label={label}
      className="w-full h-8 rounded-lg border-[color:var(--border)] bg-white text-[13px]"
    >
      <SelectValue>{children}</SelectValue>
    </SelectTrigger>
  );
}
