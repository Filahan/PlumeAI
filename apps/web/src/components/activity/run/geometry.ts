/** Everything the run detail page reads out of one `RunWithAutomation`.
 *
 *  Pure on purpose — no React, no fetching, no `Date.now()`. The gantt is the whole
 *  point of the page, so the arithmetic that places its bars lives on its own where it
 *  can be reasoned about: the caller passes `now` in, and a run still in flight lays out
 *  against a clock that is not moving underneath it.
 */

import type { RunStep, RunWithAutomation, TraceEntry } from '@/lib/automations/types';
import { isRunActive } from '@/lib/automations/types';

/** How wide a bar is drawn when the attempt it stands for took no time at all.
 *
 *  Not cosmetic: a step that fails on a bad argument fails in ~40ms and then waits 10s
 *  before trying again, so the three real bars of a retried step are 0.09% of the run
 *  each. Drawn honestly they would be invisible, and the lane would read as "nothing
 *  happened here" — which is the opposite of the truth. */
const MIN_SEGMENT_PCT = 1.2;

/** One attempt of one step, placed against the run's own timeline. */
export interface AttemptSegment {
  /** 1-based, matching the trace's `n`. */
  n: number;
  failed: boolean;
  /** Percentages of the whole run, ready for `left` / `width`. */
  leftPct: number;
  widthPct: number;
  /** What this attempt is believed to have taken. Derived, not measured — see
   *  `attemptSegments` for why. */
  durationMs: number;
  error: string | null;
}

/** The backoff wait between two attempts — the dashed connector in the track. */
export interface WaitSegment {
  leftPct: number;
  widthPct: number;
  seconds: number;
}

/** One lane of the gantt: a step, its attempts, and the waits between them. */
export interface StepLane {
  step: RunStep;
  /** 1-based position in the run, for "step 3 of 4". */
  position: number;
  segments: AttemptSegment[];
  waits: WaitSegment[];
  /** How many times the step was tried. 1 for everything that worked first time. */
  attempts: number;
  /** False for a step the run never reached — it gets the words "never ran". */
  ran: boolean;
  /** True when the per-attempt widths were derived by dividing the step's span rather
   *  than measured — see `attemptSegments`. A single bar spanning the whole step is not
   *  estimated: that one is exactly what the API reported. */
  estimated: boolean;
}

/** The waits a run actually sat through, in the order it sat through them — what the
 *  gantt's footer reports as the retry policy. */
export interface RunGeometry {
  /** The moment `left: 0%` stands for. */
  startedAt: number;
  /** What 100% of the track is worth. Never zero, so nothing divides by it. */
  totalMs: number;
  lanes: StepLane[];
  /** The longest chain of backoff waits any one step went through, in seconds. */
  backoffSeconds: number[];
}

/** The retry entries of a step's trace, oldest first. */
function attemptEntries(trace: TraceEntry[]): Extract<TraceEntry, { kind: 'attempt' }>[] {
  return trace.filter(
    (entry): entry is Extract<TraceEntry, { kind: 'attempt' }> => entry.kind === 'attempt'
  );
}

/** The backoff waits a step sat through, in ms.
 *
 *  The executor appends one `attempt` entry per *failed* attempt, and only gives it a
 *  `retryInSeconds` when it is actually going to wait and try again — so the number of
 *  waits is exactly the number of retries, whether the step eventually succeeded or
 *  gave up. (`app/services/executor.py::_run_one`.) */
function backoffMs(step: RunStep): number[] {
  return attemptEntries(step.trace)
    .map((entry) => entry.retryInSeconds)
    .filter((s): s is number => typeof s === 'number' && s > 0)
    .map((s) => s * 1000);
}

/** When a step stopped, as far as this render is concerned. */
function stepEnd(step: RunStep, now: number): number {
  if (step.endedAt != null) return step.endedAt;
  if (step.startedAt == null) return now;
  if (step.status === 'running') return Math.max(now, step.startedAt);
  return step.startedAt + (step.durationMs ?? 0);
}

/** Split one step into per-attempt bars.
 *
 *  What the API actually gives us: the step's `startedAt`, `endedAt`/`durationMs`, its
 *  final `attempt` number, and a trace of `{kind: "attempt", n, error, retryInSeconds}`
 *  entries. What it does **not** give us is a timestamp per attempt — so the attempts
 *  themselves cannot be measured, only reconstructed:
 *
 *      step span = attempt₁ + wait₁ + attempt₂ + wait₂ + … + attemptₙ
 *
 *  The waits are known exactly (`retryInSeconds`), so the work left over — the span
 *  minus every wait — is what the attempts shared, and it is divided evenly between
 *  them. That is honest for the failure this actually happens to (an argument the tool
 *  rejects, rejected just as fast every time) and it is at worst a plausible ordering
 *  for anything else: the bars are in the right places and the *waits*, which are the
 *  part worth looking at, are exact.
 *
 *  When the trace carries no waits — one attempt, or a step from before traces — the
 *  step gets a single bar spanning it, and that bar is exact. */
function attemptSegments(
  step: RunStep,
  runStart: number,
  totalMs: number,
  now: number
): Pick<StepLane, 'segments' | 'waits' | 'estimated'> {
  const pct = (ms: number) => (ms / totalMs) * 100;
  const startedAt = step.startedAt;
  if (startedAt == null) return { segments: [], waits: [], estimated: false };

  const offset = startedAt - runStart;
  const spanMs = Math.max(stepEnd(step, now) - startedAt, 0);
  const waits = backoffMs(step);
  const entries = attemptEntries(step.trace);
  const totalWait = waits.reduce((sum, ms) => sum + ms, 0);
  const workMs = spanMs - totalWait;
  const failedStep = step.status === 'failed';

  // Not enough to split on, or a span that cannot hold the waits it claims (a clock that
  // disagrees with itself): one bar for the whole step rather than a fiction.
  if (waits.length === 0 || workMs <= 0) {
    return {
      segments: [
        {
          n: step.attempt || 1,
          failed: failedStep,
          leftPct: pct(offset),
          widthPct: pct(spanMs),
          durationMs: spanMs,
          error: step.error,
        },
      ],
      waits: [],
      estimated: false,
    };
  }

  const count = waits.length + 1;
  const each = workMs / count;
  const segments: AttemptSegment[] = [];
  const gaps: WaitSegment[] = [];
  let cursor = offset;

  for (let i = 0; i < count; i += 1) {
    const last = i === count - 1;
    segments.push({
      n: i + 1,
      // Every attempt but the last one failed by definition; the last one failed only if
      // the step did.
      failed: !last || failedStep,
      leftPct: pct(cursor),
      widthPct: pct(each),
      durationMs: each,
      error: entries[i]?.error ?? (last ? step.error : null),
    });
    cursor += each;
    if (!last) {
      gaps.push({ leftPct: pct(cursor), widthPct: pct(waits[i]), seconds: waits[i] / 1000 });
      cursor += waits[i];
    }
  }

  return { segments, waits: gaps, estimated: true };
}

/** Widen the hair-thin bars, then walk left to right pushing anything that now overlaps
 *  or overflows back into the track. Nothing ever leaves `[0, 100]`, and the attempts
 *  keep their order even when every one of them had to be widened. */
function fitSegments(segments: AttemptSegment[], waits: WaitSegment[]): void {
  let end = 0;
  for (const segment of segments) {
    const width = Math.min(Math.max(segment.widthPct, MIN_SEGMENT_PCT), 100);
    const left = Math.min(Math.max(segment.leftPct, end), 100 - width);
    segment.leftPct = Math.max(left, 0);
    segment.widthPct = width;
    end = segment.leftPct + width;
  }
  // The dashes join the bars they sit between, so they are re-read off the fitted bars
  // rather than kept where the raw arithmetic put them.
  for (let i = 0; i < waits.length; i += 1) {
    const before = segments[i];
    const after = segments[i + 1];
    if (!before || !after) {
      waits[i].widthPct = 0;
      continue;
    }
    const left = before.leftPct + before.widthPct;
    waits[i].leftPct = left;
    waits[i].widthPct = Math.max(after.leftPct - left, 0);
  }
}

/** The whole gantt, in percentages, from one run detail. */
export function runGeometry(run: RunWithAutomation, now: number): RunGeometry {
  const startedAt = run.startedAt ?? run.createdAt;
  const endedAt = run.endedAt ?? (isRunActive(run.status) ? Math.max(now, startedAt) : startedAt);
  const measured = run.durationMs ?? endedAt - startedAt;
  // Never zero: every placement divides by this, and a run that took under a millisecond
  // is still a run with steps to draw.
  const totalMs = Math.max(measured, 1);

  const lanes: StepLane[] = run.steps.map((step, index) => {
    const { segments, waits, estimated } = attemptSegments(step, startedAt, totalMs, now);
    fitSegments(segments, waits);
    return {
      step,
      position: index + 1,
      segments,
      waits,
      attempts: Math.max(step.attempt || 1, backoffMs(step).length + 1),
      ran: step.startedAt != null,
      estimated,
    };
  });

  let backoffSeconds: number[] = [];
  for (const lane of lanes) {
    const seconds = lane.waits.map((wait) => wait.seconds);
    if (seconds.length > backoffSeconds.length) backoffSeconds = seconds;
  }

  return { startedAt, totalMs, lanes, backoffSeconds };
}

// ─── Words ──────────────────────────────────────────────────────────────────────────

/** The step the run stopped on: the one that failed, or the filter that said stop. */
export function failedLane(lanes: StepLane[], stoppedByStepId: string | null): StepLane | null {
  return (
    lanes.find((lane) => lane.step.status === 'failed') ??
    (stoppedByStepId ? (lanes.find((lane) => lane.step.stepId === stoppedByStepId) ?? null) : null)
  );
}

/** Which lane the panels open on: the failure if there is one, else the last step that
 *  actually ran, else the first. */
export function defaultLaneId(lanes: StepLane[], stoppedByStepId: string | null): string | null {
  if (lanes.length === 0) return null;
  const failed = failedLane(lanes, stoppedByStepId);
  if (failed) return failed.step.stepId;
  const ran = [...lanes].reverse().find((lane) => lane.ran);
  return (ran ?? lanes[0]).step.stepId;
}

const TRIGGER_PHRASE: Record<string, string> = {
  schedule: 'Started by the schedule',
  manual: 'Started by hand',
  test: 'Started as a test',
};

export function triggerPhrase(trigger: string): string {
  return TRIGGER_PHRASE[trigger] ?? 'Started by hand';
}

/** The bold first line of the error card: the step, named the way the user named it.
 *
 *  Deliberately not a guess at *what* the step does — "could not send the message" is
 *  only true of a Discord step. The step's own name carries that. */
export function failureHeadline(step: RunStep | null): string {
  if (!step) return 'The run could not finish';
  const verb = step.type === 'action' ? 'could not run' : 'could not finish';
  return `“${step.name}” ${verb}`;
}

/** Quoted names inside an error message: `requires "channel_id" and "content"`. */
const QUOTED = /["'`]([A-Za-z_][A-Za-z0-9_.-]{0,39})["'`]/g;

/** The input field an error is complaining about, or null.
 *
 *  Only ever a field the step really sent — a name quoted in the message is a candidate,
 *  a name quoted in the message *and* present in `resolvedInput` is an answer. That is
 *  what keeps "Fix this field" from pointing at a field that does not exist. */
export function errorField(step: RunStep | null): string | null {
  if (!step?.error || !step.resolvedInput) return null;
  const sent = new Set(Object.keys(step.resolvedInput));
  if (sent.size === 0) return null;
  for (const match of step.error.matchAll(QUOTED)) {
    const name = match[1];
    if (sent.has(name)) return name;
    const leaf = name.split('.').pop();
    if (leaf && sent.has(leaf)) return leaf;
  }
  return null;
}

/** `channel_id` → `Channel id` — the field as its label reads in the editor. */
export function fieldLabel(field: string): string {
  const words = field.replace(/[_-]+/g, ' ').replace(/([a-z])([A-Z])/g, '$1 $2').trim();
  return words.charAt(0).toUpperCase() + words.slice(1).toLowerCase();
}

/** The gantt footer's second half: the backoff this run actually used. */
export function retryPolicyLine(backoffSeconds: number[]): string {
  if (backoffSeconds.length === 0) return 'No step needed a second try.';
  const parts = backoffSeconds.map((s) => `${s}s`);
  if (parts.length === 1) return `The retry waited ${parts[0]}.`;
  return `Retries wait ${parts.slice(0, -1).join(', ')}, then ${parts[parts.length - 1]}.`;
}
