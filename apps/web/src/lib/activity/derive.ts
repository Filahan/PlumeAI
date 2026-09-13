/** Everything the Activity section reads out of a flat list of runs.
 *
 *  Pure on purpose — no React, no fetching, no `Date.now()`: the caller passes `now` in,
 *  so a lane layout can be reasoned about (and re-derived on a timer) without the clock
 *  moving underneath it.
 */

import { startOfDay } from '@/lib/automations/format';
import { isRunActive, type RunListItem, type RunStatus } from '@/lib/automations/types';

const DAY_MS = 86_400_000;

/** How wide a mark is drawn when the run it stands for took no time at all — a 900ms run
 *  is 0.001% of a day, which is nothing. Matches the design's 1.4%. */
const MIN_MARK_PCT = 1.4;

/** Squares per automation in the grid, oldest left. */
export const MAX_SQUARES = 20;

/** A run has to fail this many times in a row before the banner speaks up. */
export const FAILING_STREAK_MIN = 2;

// ─── Range ──────────────────────────────────────────────────────────────────────────

export type ActivityRange = 'today' | '7d' | '30d';

export const ACTIVITY_RANGES: { id: ActivityRange; label: string }[] = [
  { id: 'today', label: 'Today' },
  { id: '7d', label: '7 days' },
  { id: '30d', label: '30 days' },
];

/** The oldest moment a range includes. "Today" starts at local midnight; the others are
 *  rolling windows, because "7 days" means the last seven days of activity. */
export function rangeStart(range: ActivityRange, now: number): number {
  if (range === 'today') return startOfDay(now);
  return now - (range === '7d' ? 7 : 30) * DAY_MS;
}

/** When a run happened. `startedAt` is null while a run is still queued, and then the
 *  moment it was created is the best answer. */
export function runTime(run: RunListItem): number {
  return run.startedAt ?? run.createdAt;
}

// ─── Buckets ────────────────────────────────────────────────────────────────────────

/** Runs grouped by automation, newest first inside each bucket.
 *
 *  The feed already arrives newest first, but it is sorted again here so the grid does
 *  not depend on that: a square strip that silently reverses is hard to notice and
 *  impossible to trust. */
export function runsByAutomation(runs: RunListItem[]): Map<string, RunListItem[]> {
  const byId = new Map<string, RunListItem[]>();
  for (const run of runs) {
    const bucket = byId.get(run.automationId);
    if (bucket) bucket.push(run);
    else byId.set(run.automationId, [run]);
  }
  for (const bucket of byId.values()) {
    bucket.sort((a, b) => runTime(b) - runTime(a));
  }
  return byId;
}

// ─── Needs attention ────────────────────────────────────────────────────────────────

export interface FailingStreak {
  automationId: string;
  automationName: string;
  /** Consecutive failures at the head of that automation's history. */
  count: number;
  /** The most recent failed run — what "See what happened" opens. */
  latestRun: RunListItem;
  /** When the streak began: the start of its oldest failure. */
  since: number;
  /** Step id every attempt stops on, when they all agree on one. */
  stoppedByStepId: string | null;
}

/** Count the failures at the head of one automation's history.
 *
 *  A run that is still going does not break a streak (it has not failed *yet*), so
 *  active runs are skipped rather than counted — otherwise the banner would blink off
 *  the moment the next attempt starts and back on when it fails. */
function headStreak(bucket: RunListItem[]): RunListItem[] {
  const failures: RunListItem[] = [];
  for (const run of bucket) {
    if (isRunActive(run.status)) continue;
    if (run.status !== 'failed') break;
    failures.push(run);
  }
  return failures;
}

/** The automation most in need of attention, or `null` when nothing is failing twice
 *  over. Ties go to the automation that failed most recently. */
export function failingStreak(runs: RunListItem[]): FailingStreak | null {
  let worst: FailingStreak | null = null;

  for (const bucket of runsByAutomation(runs).values()) {
    const failures = headStreak(bucket);
    if (failures.length < FAILING_STREAK_MIN) continue;

    const latestRun = failures[0];
    const oldest = failures[failures.length - 1];
    const stepIds = new Set(failures.map((r) => r.stoppedByStepId));
    const candidate: FailingStreak = {
      automationId: latestRun.automationId,
      automationName: latestRun.automationName,
      count: failures.length,
      latestRun,
      since: runTime(oldest),
      stoppedByStepId: stepIds.size === 1 ? (latestRun.stoppedByStepId ?? null) : null,
    };
    if (
      !worst ||
      candidate.count > worst.count ||
      (candidate.count === worst.count && runTime(candidate.latestRun) > runTime(worst.latestRun))
    ) {
      worst = candidate;
    }
  }

  return worst;
}

// ─── Day timeline ───────────────────────────────────────────────────────────────────

export interface DayMark {
  runId: string;
  automationId: string;
  automationName: string;
  status: RunStatus;
  startedAt: number;
  durationMs: number | null;
  /** Percentages of the whole day, ready for `left` / `width`. */
  leftPct: number;
  widthPct: number;
}

export interface DayLane {
  automationId: string;
  automationName: string;
  marks: DayMark[];
}

/** One lane per automation that ran today, each mark placed by its start time.
 *
 *  Marks are widened to `MIN_MARK_PCT` so a two-second run is still a thing you can see
 *  and click, and pushed back inside the track so a run that is still going at 23:59 does
 *  not overflow it. Lanes come back in the order they first ran. */
export function dayLanes(runs: RunListItem[], now: number): DayLane[] {
  const dayStart = startOfDay(now);
  const dayEnd = dayStart + DAY_MS;
  const lanes = new Map<string, DayLane>();

  for (const run of runs) {
    const startedAt = run.startedAt;
    if (startedAt == null || startedAt < dayStart || startedAt >= dayEnd) continue;

    // A run in flight has no duration yet; it has lasted until now.
    const elapsed = run.durationMs ?? (isRunActive(run.status) ? Math.max(0, now - startedAt) : 0);
    // Width first, then placement: a run that starts at 23:59 keeps its minimum width and
    // is nudged left to fit, rather than hanging off the end of the track.
    const widthPct = Math.min(Math.max((elapsed / DAY_MS) * 100, MIN_MARK_PCT), 100);
    const leftPct = Math.min(((startedAt - dayStart) / DAY_MS) * 100, 100 - widthPct);

    const mark: DayMark = {
      runId: run.id,
      automationId: run.automationId,
      automationName: run.automationName,
      status: run.status,
      startedAt,
      durationMs: run.durationMs,
      leftPct,
      widthPct,
    };

    const lane = lanes.get(run.automationId);
    if (lane) lane.marks.push(mark);
    else {
      lanes.set(run.automationId, {
        automationId: run.automationId,
        automationName: run.automationName,
        marks: [mark],
      });
    }
  }

  const ordered = Array.from(lanes.values());
  for (const lane of ordered) lane.marks.sort((a, b) => a.startedAt - b.startedAt);
  ordered.sort((a, b) => a.marks[0].startedAt - b.marks[0].startedAt);
  return ordered;
}

/** The axis above the lanes: six evenly spaced labels, 00:00 through 20:00. */
export const HOUR_TICKS = ['00:00', '04:00', '08:00', '12:00', '16:00', '20:00'];

// ─── Links ──────────────────────────────────────────────────────────────────────────

/** Where a square, a mark or the banner's button sends you: the automation's editor,
 *  with the run it should select. */
export function runHref(automationId: string, runId: string): string {
  return `/automations/${encodeURIComponent(automationId)}?run=${encodeURIComponent(runId)}`;
}
