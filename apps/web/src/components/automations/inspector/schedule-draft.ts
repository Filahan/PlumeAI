/** The schedule editor's working state, and the rules for turning it back into a
 *  `Trigger`.
 *
 *  The dialog edits a draft rather than the document: nothing is written until "Save
 *  schedule", so switching between "every weekday" and "every 15 minutes" and back
 *  leaves the automation exactly as it was. Pure — no React, no store. */

import type { Trigger } from '@/lib/automations/types';
import { browserTimezone, parseCronPreset } from './next-runs';

export type DraftMode = 'manual' | 'interval' | 'cron';

export interface ScheduleDraft {
  mode: DraftMode;
  /** `interval` mode. Clamped to the document schema's 1…10080 on the way out. */
  everyMinutes: number;
  /** `cron` mode: the time of day it fires. */
  hour: number;
  minute: number;
  /** The days it fires on — `null` means every day. */
  dows: number[] | null;
  timezone: string;
  /** The raw expression, authoritative while `custom` is on. */
  cron: string;
  /** "Write it as cron" is open and what is in the box wins over the pills. */
  custom: boolean;
}

export const DEFAULT_CRON = '0 9 * * *';
export const DEFAULT_MINUTES = 15;
const MAX_MINUTES = 10080;

const DAY_NAMES = [
  'Sunday',
  'Monday',
  'Tuesday',
  'Wednesday',
  'Thursday',
  'Friday',
  'Saturday',
];
const SHORT_DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

/** Day sets ↔ the cron weekday field. `1-5` rather than `1,2,3,4,5` on purpose: it is
 *  the shape the backend's `describe_trigger` recognises as "weekdays". */
export function dowField(dows: number[] | null): string {
  if (dows === null || dows.length === 0) return '*';
  const sorted = [...new Set(dows)].sort((a, b) => a - b);
  if (sorted.length === 7) return '*';
  if (sorted.join(',') === '1,2,3,4,5') return '1-5';
  return sorted.join(',');
}

/** The inverse, via the evaluator's own parser so the two can never drift. */
export function parseDowField(field: string): number[] | null {
  return parseCronPreset(`0 0 * * ${field}`)?.dows ?? null;
}

/** "day" / "weekday" / "weekend day" / "Monday" / "Mon, Wed & Fri" — the noun the
 *  sentence reads after "every". */
export function daysPhrase(dows: number[] | null): string {
  const field = dowField(dows);
  if (field === '*') return 'day';
  if (field === '1-5') return 'weekday';
  if (field === '0,6') return 'weekend day';
  const days = dows ?? [];
  if (days.length === 1) return DAY_NAMES[days[0]];
  const names = [...days].sort((a, b) => a - b).map((d) => SHORT_DAYS[d]);
  return `${names.slice(0, -1).join(', ')} & ${names[names.length - 1]}`;
}

export function dayName(day: number): string {
  return DAY_NAMES[day] ?? DAY_NAMES[0];
}

export function shortDay(day: number): string {
  return SHORT_DAYS[day] ?? SHORT_DAYS[0];
}

export function clockLabel(hour: number, minute: number): string {
  return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`;
}

/** The expression the draft currently means. */
export function draftCron(draft: ScheduleDraft): string {
  if (draft.custom) return draft.cron.trim();
  return `${draft.minute} ${draft.hour} * * ${dowField(draft.dows)}`;
}

/** A draft built from whatever the automation has now. */
export function draftFromTrigger(
  trigger: Trigger | null | undefined,
  fallbackTimezone: string = browserTimezone()
): ScheduleDraft {
  const settings = trigger && trigger.type === 'schedule' ? trigger.settings : null;
  const cron = settings?.mode === 'cron' ? settings.cron : DEFAULT_CRON;
  const shape = parseCronPreset(cron);
  return {
    mode: !trigger || trigger.type === 'manual' ? 'manual' : settings?.mode === 'interval' ? 'interval' : 'cron',
    everyMinutes: settings?.mode === 'interval' ? settings.every_minutes : DEFAULT_MINUTES,
    hour: shape?.hour ?? 9,
    minute: shape?.minute ?? 0,
    dows: shape?.dows ?? null,
    timezone: settings?.timezone ?? fallbackTimezone,
    cron,
    // An expression the pills cannot represent opens the cron box rather than being
    // silently rewritten into something else the moment anything is touched.
    custom: settings?.mode === 'cron' && shape === null,
  };
}

/** The `set_trigger` payload. Exactly one of `cron` / `every_minutes` is ever sent —
 *  the document schema rejects both. */
export function draftToTrigger(draft: ScheduleDraft): Trigger {
  if (draft.mode === 'manual') return { type: 'manual' };
  if (draft.mode === 'interval') {
    return {
      type: 'schedule',
      settings: {
        mode: 'interval',
        every_minutes: Math.min(MAX_MINUTES, Math.max(1, Math.round(draft.everyMinutes))),
      },
    };
  }
  return {
    type: 'schedule',
    settings: { mode: 'cron', cron: draftCron(draft), timezone: draft.timezone },
  };
}

/** What the draft says, in one sentence — the inspector's read-only line. */
export function draftSentence(draft: ScheduleDraft): string {
  if (draft.mode === 'manual') return 'Only when you press Run.';
  if (draft.mode === 'interval') {
    const n = Math.round(draft.everyMinutes);
    return `Every ${n} ${n === 1 ? 'minute' : 'minutes'}.`;
  }
  const shape = parseCronPreset(draftCron(draft));
  if (!shape) return `Cron: ${draftCron(draft)} (${draft.timezone}).`;
  if (shape.hour === null) {
    return `Every hour at ${String(shape.minute).padStart(2, '0')} past, ${draft.timezone}.`;
  }
  const time = clockLabel(shape.hour, shape.minute);
  return `Every ${daysPhrase(shape.dows)} at ${time}, ${draft.timezone}.`;
}

/** The muted line under "That means", when the schedule quietly skips days. */
export function draftCaveat(draft: ScheduleDraft): string | null {
  if (draft.mode === 'interval') return 'The clock restarts after each run, so these shift.';
  if (draft.mode !== 'cron') return null;
  const dows = parseCronPreset(draftCron(draft))?.dows ?? null;
  if (dows === null) return null;
  const field = dowField(dows);
  if (field === '1-5') return 'Saturdays and Sundays are skipped.';
  if (field === '0,6') return 'Monday to Friday are skipped.';
  const skipped = [0, 1, 2, 3, 4, 5, 6].filter((d) => !dows.includes(d));
  if (skipped.length === 0) return null;
  return `${skipped.map(shortDay).join(', ')} ${skipped.length === 1 ? 'is' : 'are'} skipped.`;
}
