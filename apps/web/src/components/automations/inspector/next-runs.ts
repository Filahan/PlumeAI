/** The client-side schedule evaluator.
 *
 *  Two callers, one set of rules: the schedule editor's "That means" preview (the next
 *  three fire times) and the Schedules tab's 24-hour plan (`lib/activity/plan.ts`), which
 *  enumerates the same shapes across a window.
 *
 *  Only the shapes the editor itself can produce are understood — hourly at a minute,
 *  daily, weekdays, and any set of weekdays — plus plain intervals; anything else is
 *  "custom" and the server's `nextRunAt` remains the source of truth. No cron library:
 *  parsing five fields we wrote ourselves does not justify the dependency.
 *
 *  Pure functions — no React, no store. */

export interface CronShape {
  minute: number;
  /** `null` = every hour. */
  hour: number | null;
  /** `null` = every day, else the allowed `Date#getDay()` values, ascending. */
  dows: number[] | null;
}

export function browserTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}

/** One `1`, `1-5` or `0,3,6` term of the weekday field. Cron allows 7 for Sunday. */
const DOW_TOKEN = /^([0-7])(?:-([0-7]))?$/;

/** `null` for `*` (every day), a sorted day list for anything we understand, and
 *  `undefined` for a weekday field this evaluator cannot read. */
function parseDows(raw: string): number[] | null | undefined {
  if (raw === '*') return null;
  const days = new Set<number>();
  for (const token of raw.split(',')) {
    const match = DOW_TOKEN.exec(token);
    if (!match) return undefined;
    const from = Number(match[1]);
    const to = match[2] === undefined ? from : Number(match[2]);
    if (to < from) return undefined;
    for (let day = from; day <= to; day += 1) days.add(day % 7);
  }
  return days.size > 0 ? [...days].sort((a, b) => a - b) : undefined;
}

/** Parse the cron expressions this editor writes. `null` for anything else. */
export function parseCronPreset(cron: string): CronShape | null {
  const parts = cron.trim().split(/\s+/);
  if (parts.length !== 5) return null;
  const [rawMinute, rawHour, dom, month, rawDow] = parts;
  if (dom !== '*' || month !== '*') return null;
  if (!/^\d{1,2}$/.test(rawMinute)) return null;
  const minute = Number(rawMinute);
  if (minute > 59) return null;

  let hour: number | null = null;
  if (rawHour !== '*') {
    if (!/^\d{1,2}$/.test(rawHour)) return null;
    hour = Number(rawHour);
    if (hour > 23) return null;
  }

  const dows = parseDows(rawDow);
  if (dows === undefined) return null;

  // "every hour, but only on Mondays" is expressible in cron but not in this editor.
  if (hour === null && dows !== null) return null;
  return { minute, hour, dows };
}

interface WallClock {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
}

const FIELDS = ['year', 'month', 'day', 'hour', 'minute', 'second'] as const;

function partsIn(instant: number, timezone: string): Record<string, number> {
  const formatter = new Intl.DateTimeFormat('en-US', {
    timeZone: timezone,
    hour12: false,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
  const out: Record<string, number> = {};
  for (const part of formatter.formatToParts(new Date(instant))) {
    if ((FIELDS as readonly string[]).includes(part.type)) {
      // `hour` can come back as "24" for midnight in some locales/engines.
      const value = Number(part.value);
      out[part.type] = part.type === 'hour' ? value % 24 : value;
    }
  }
  return out;
}

/** The zone's UTC offset (ms) at a given instant. */
function offsetAt(instant: number, timezone: string): number {
  const p = partsIn(instant, timezone);
  const asUtc = Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute, p.second);
  return asUtc - instant;
}

/** Wall-clock fields in `timezone` → the UTC instant they name (DST-corrected). */
function wallToInstant(wall: WallClock, timezone: string): number {
  const naive = Date.UTC(wall.year, wall.month - 1, wall.day, wall.hour, wall.minute);
  const first = naive - offsetAt(naive, timezone);
  // One correction pass is enough: the offset can only be wrong when the naive guess
  // landed on the other side of a transition.
  return naive - offsetAt(first, timezone);
}

/** What the clock on the wall in `timezone` reads at `instant`. */
function wallAt(instant: number, timezone: string): WallClock {
  const p = partsIn(instant, timezone);
  return { year: p.year, month: p.month, day: p.day, hour: p.hour, minute: p.minute };
}

/** The next `count` firing instants of a preset cron shape, strictly after `from`.
 *
 *  `from` is a parameter rather than a read of the clock so the same walk answers both
 *  "the next three runs" and "every run between now and this time tomorrow". */
export function nextCronRuns(
  shape: CronShape,
  timezone: string,
  count = 3,
  from = Date.now()
): number[] {
  if (count <= 0) return [];
  const now = wallAt(from, timezone);
  const out: number[] = [];

  const emit = (cursor: Date, hour: number) =>
    out.push(
      wallToInstant(
        {
          year: cursor.getUTCFullYear(),
          month: cursor.getUTCMonth() + 1,
          day: cursor.getUTCDate(),
          hour,
          minute: shape.minute,
        },
        timezone
      )
    );

  if (shape.hour === null) {
    // Hourly at `minute`.
    const cursor = new Date(Date.UTC(now.year, now.month - 1, now.day, now.hour));
    if (now.minute >= shape.minute) cursor.setUTCHours(cursor.getUTCHours() + 1);
    for (let i = 0; i < count; i += 1) {
      emit(cursor, cursor.getUTCHours());
      cursor.setUTCHours(cursor.getUTCHours() + 1);
    }
    return out;
  }

  const hour = shape.hour;
  const cursor = new Date(Date.UTC(now.year, now.month - 1, now.day));
  const passedToday = now.hour > hour || (now.hour === hour && now.minute >= shape.minute);
  if (passedToday) cursor.setUTCDate(cursor.getUTCDate() + 1);

  // At most a year of days — a weekly schedule needs 15 hops for three runs.
  for (let guard = 0; guard < 400 && out.length < count; guard += 1) {
    if (shape.dows === null || shape.dows.includes(cursor.getUTCDay())) emit(cursor, hour);
    cursor.setUTCDate(cursor.getUTCDate() + 1);
  }
  return out;
}

/** Every firing instant in `[from, until)` — the Schedules tab's 24-hour plan.
 *
 *  The walk is bounded by the shape's own period rather than by `cap` alone: a weekly
 *  schedule asked for 60 runs would step a year of days for two useful answers. */
export function cronRunsWithin(
  shape: CronShape,
  timezone: string,
  from: number,
  until: number,
  cap = 60
): number[] {
  if (until <= from) return [];
  const period = shape.hour === null ? 3_600_000 : 86_400_000;
  const count = Math.max(1, Math.min(cap, Math.ceil((until - from) / period) + 1));
  return nextCronRuns(shape, timezone, count, from).filter((instant) => instant < until);
}

/** Interval triggers fire relative to the last run, so this is "from now" — close
 *  enough for a preview, and labelled as approximate in the UI. */
export function nextIntervalRuns(everyMinutes: number, count = 3): number[] {
  const step = Math.max(1, Math.round(everyMinutes)) * 60_000;
  const base = Date.now();
  return Array.from({ length: count }, (_, i) => base + step * (i + 1));
}

/** "Tue 14 Jan, 09:00" in the trigger's own timezone. */
export function formatRunTime(instant: number, timezone: string): string {
  try {
    return new Intl.DateTimeFormat(undefined, {
      timeZone: timezone,
      weekday: 'short',
      day: 'numeric',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    }).format(new Date(instant));
  } catch {
    return new Date(instant).toISOString();
  }
}
