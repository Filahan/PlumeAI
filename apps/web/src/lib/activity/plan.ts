/** What the next 24 hours actually look like, computed in the browser.
 *
 *  `GET /schedules` reports one `nextRunAt` per automation; the strip at the top of the
 *  Schedules tab needs every run in the window, so the shapes are expanded here from
 *  `mode` / `cron` / `everyMinutes` / `timezone`. Cron is handed to the editor's own
 *  evaluator (`next-runs.ts`) rather than forked — one set of rules, two views.
 *
 *  Pure on purpose: `now` is passed in, so a strip can be re-derived on a timer without
 *  the clock moving underneath it, and the whole thing is testable from a script.
 */

import {
  browserTimezone,
  cronRunsWithin,
  parseCronPreset,
} from '@/components/automations/inspector/next-runs';
import type { ScheduleItem } from '@/lib/automations/types';

export const HORIZON_MS = 86_400_000;

/** Marks one automation may contribute to the strip.
 *
 *  A 1-minute schedule would otherwise draw 1440 of them into 1120px — a grey bar, not a
 *  plan. Past this many the runs are thinned (every Nth is drawn) rather than truncated,
 *  so the marks still span the whole window; `planStride` says by how much, and the
 *  caption says so out loud. */
export const MAX_MARKS_PER_AUTOMATION = 60;

export interface PlannedRun {
  automationId: string;
  name: string;
  /** Epoch ms. */
  at: number;
}

/** Two or more planned runs landing in the same minute — they queue behind each other. */
export interface Collision {
  /** The minute they share, as epoch ms. */
  at: number;
  runs: PlannedRun[];
}

function stepMs(everyMinutes: number | null): number | null {
  if (everyMinutes === null || !Number.isFinite(everyMinutes) || everyMinutes < 1) return null;
  return Math.round(everyMinutes) * 60_000;
}

/** How many real runs one drawn mark stands for. 1 means every run is drawn.
 *
 *  Only intervals ever thin out: the cron shapes this app can write top out at 25 runs a
 *  day (hourly), which fits the strip as it is. */
export function planStride(
  schedule: ScheduleItem,
  now: number,
  horizonMs: number = HORIZON_MS
): number {
  if (schedule.mode !== 'interval' || !schedule.enabled) return 1;
  const step = stepMs(schedule.everyMinutes);
  if (step === null || schedule.nextRunAt === null) return 1;
  const span = now + horizonMs - Math.max(schedule.nextRunAt, now);
  if (span <= 0) return 1;
  const count = Math.floor(span / step) + 1;
  return count <= MAX_MARKS_PER_AUTOMATION
    ? 1
    : Math.ceil(count / MAX_MARKS_PER_AUTOMATION);
}

/** The single answer the server already gave us, when the shape is one we cannot expand
 *  (a hand-written cron, or an interval with no next run yet). */
function serverAnswer(schedule: ScheduleItem, now: number, until: number): number[] {
  const at = schedule.nextRunAt;
  return at !== null && at >= now && at < until ? [at] : [];
}

function instantsOf(
  schedule: ScheduleItem,
  now: number,
  horizonMs: number,
  fallbackTimezone: string
): number[] {
  if (!schedule.enabled) return [];
  const until = now + horizonMs;

  if (schedule.mode === 'interval') {
    const step = stepMs(schedule.everyMinutes);
    const start = schedule.nextRunAt;
    if (step === null || start === null) return serverAnswer(schedule, now, until);
    const stride = planStride(schedule, now, horizonMs) * step;
    const out: number[] = [];
    for (
      let at = start;
      at < until && out.length < MAX_MARKS_PER_AUTOMATION;
      at += stride
    ) {
      if (at >= now) out.push(at);
    }
    return out;
  }

  const shape = schedule.cron ? parseCronPreset(schedule.cron) : null;
  if (!shape) return serverAnswer(schedule, now, until);
  return cronRunsWithin(
    shape,
    schedule.timezone ?? fallbackTimezone,
    now,
    until,
    MAX_MARKS_PER_AUTOMATION
  );
}

/** Every run planned between `now` and `now + horizonMs`, soonest first.
 *
 *  Paused schedules contribute nothing — that is what paused means. `fallbackTimezone`
 *  is the workspace zone a schedule without one of its own inherits. */
export function plannedRuns(
  schedules: ScheduleItem[],
  now: number,
  horizonMs: number = HORIZON_MS,
  fallbackTimezone: string = browserTimezone()
): PlannedRun[] {
  const out: PlannedRun[] = [];
  for (const schedule of schedules) {
    for (const at of instantsOf(schedule, now, horizonMs, fallbackTimezone)) {
      out.push({ automationId: schedule.automationId, name: schedule.name, at });
    }
  }
  out.sort((a, b) => a.at - b.at);
  return out;
}

/** Runs sharing a minute, grouped. The scheduler starts them one after the other, so
 *  these are the only marks worth calling out on the strip. */
export function collisions(runs: PlannedRun[]): Collision[] {
  const byMinute = new Map<number, PlannedRun[]>();
  for (const run of runs) {
    const minute = Math.floor(run.at / 60_000) * 60_000;
    const bucket = byMinute.get(minute);
    if (bucket) bucket.push(run);
    else byMinute.set(minute, [run]);
  }
  return [...byMinute.entries()]
    .filter(([, bucket]) => bucket.length > 1)
    .map(([at, bucket]) => ({ at, runs: bucket }))
    .sort((a, b) => a.at - b.at);
}

/** Where a mark sits on the strip: its distance from now as a percentage of the window. */
export function markLeftPct(at: number, now: number, horizonMs: number = HORIZON_MS): number {
  if (horizonMs <= 0) return 0;
  return Math.min(100, Math.max(0, ((at - now) / horizonMs) * 100));
}

/** The distinct automation names in a group, in the order they appear. */
export function namesIn(runs: PlannedRun[]): string[] {
  const seen = new Set<string>();
  const names: string[] = [];
  for (const run of runs) {
    if (seen.has(run.automationId)) continue;
    seen.add(run.automationId);
    names.push(run.name);
  }
  return names;
}

/** "A", "A and B", "A, B and C" — the collision sentence's subject. */
export function joinNames(names: string[]): string {
  if (names.length <= 1) return names[0] ?? '';
  return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`;
}
