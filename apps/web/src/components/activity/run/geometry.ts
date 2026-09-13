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
  /** How long this attempt took: recorded, or reconstructed on an old run — the lane's
   *  `estimated` flag says which. */
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
  /** Which of the two paths in `attemptSegments` drew this lane. False means every bar
   *  sits on a timestamp the executor recorded; true means the widths were reconstructed
   *  from the step's span, for a run stored before those timestamps existed. A single bar
   *  spanning the whole step is not estimated either: that one is the step's own span. */
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

/** One `attempt` entry that carries the wall-clock bounds the executor stamped on it. */
interface TimedAttempt {
  n: number;
  startedAt: number;
  endedAt: number;
  error: string | null;
  retryInSeconds: number | null;
}

/** The step's attempts, in order, only if *every* one of them was recorded with bounds.
 *
 *  All or nothing on purpose: a half-timed trace would mix bars that mean "this is when
 *  it happened" with bars that mean "this is roughly where it must have been", and there
 *  is no honest way to draw those on one track. Empty means "use the reconstruction". */
function timedAttempts(step: RunStep): TimedAttempt[] {
  const entries = attemptEntries(step.trace);
  if (entries.length === 0) return [];
  const timed: TimedAttempt[] = [];
  for (const entry of entries) {
    const { startedAt, endedAt } = entry;
    if (typeof startedAt !== 'number' || typeof endedAt !== 'number') return [];
    timed.push({
      n: entry.n,
      startedAt,
      // `endedAt` is stamped a hair after the attempt returned, so it is never before
      // the start — but a clock that stepped backwards should not produce a bar with a
      // negative width.
      endedAt: Math.max(endedAt, startedAt),
      error: entry.error ?? null,
      retryInSeconds: typeof entry.retryInSeconds === 'number' ? entry.retryInSeconds : null,
    });
  }
  return timed;
}

/** When a step stopped, as far as this render is concerned. */
function stepEnd(step: RunStep, now: number): number {
  if (step.endedAt != null) return step.endedAt;
  if (step.startedAt == null) return now;
  if (step.status === 'running') return Math.max(now, step.startedAt);
  return step.startedAt + (step.durationMs ?? 0);
}

/** The bars of a step whose attempts were all recorded with their own bounds.
 *
 *  The only thing here that is not read straight off the trace is the attempt that is
 *  *still going*: a step in flight has no entry for it yet, but the previous entry says
 *  when it ended and how long the executor meant to wait, so where the in-flight attempt
 *  began is known exactly — and it has lasted until now. Without that the lane would go
 *  quiet for the whole of a retry, which is the one moment someone is watching.
 *
 *  A step cancelled mid-attempt simply never records its last one. Nothing is invented to
 *  cover the gap: the lane shows the attempts that happened, and the row's own duration
 *  column still reports the step's full span. */
function recordedSegments(
  recorded: TimedAttempt[],
  step: RunStep,
  runStart: number,
  totalMs: number,
  now: number
): Pick<StepLane, 'segments' | 'waits' | 'estimated'> {
  const pct = (ms: number) => (ms / totalMs) * 100;
  const bounds = recorded.map((attempt) => ({
    n: attempt.n,
    startedAt: attempt.startedAt,
    endedAt: attempt.endedAt,
    error: attempt.error,
    retryInSeconds: attempt.retryInSeconds,
    inFlight: false,
  }));

  const last = recorded[recorded.length - 1];
  if (step.status === 'running' && last.retryInSeconds != null) {
    const begun = last.endedAt + last.retryInSeconds * 1000;
    if (now > begun) {
      bounds.push({
        n: last.n + 1,
        startedAt: begun,
        endedAt: Math.max(now, begun),
        error: null,
        retryInSeconds: null,
        inFlight: true,
      });
    }
  }

  const segments: AttemptSegment[] = bounds.map((attempt) => ({
    n: attempt.n,
    // The recorded attempts that are not the last one always failed — that is why there
    // was another. The last one failed only if the step did, and an in-flight one has
    // not failed yet.
    failed: attempt.inFlight ? false : attempt.error != null,
    leftPct: pct(attempt.startedAt - runStart),
    widthPct: pct(attempt.endedAt - attempt.startedAt),
    durationMs: attempt.endedAt - attempt.startedAt,
    error: attempt.error,
  }));

  const waits: WaitSegment[] = [];
  for (let i = 0; i < bounds.length - 1; i += 1) {
    const gapMs = Math.max(bounds[i + 1].startedAt - bounds[i].endedAt, 0);
    waits.push({
      leftPct: pct(bounds[i].endedAt - runStart),
      widthPct: pct(gapMs),
      // The policy's own number where it exists: "waits 10s" reads better than the
      // 10.003s the clock actually measured, and it is the number the user configured.
      seconds: bounds[i].retryInSeconds ?? Math.round(gapMs / 1000),
    });
  }

  return { segments, waits, estimated: false };
}

/** Split one step into per-attempt bars — two paths, and the lane says which it used.
 *
 *  **Recorded.** The executor stamps every `attempt` trace entry with `startedAt` and
 *  `endedAt` in the same epoch milliseconds as everything else in the payload, one entry
 *  per attempt including the winning one. When they are all there, the bars go exactly
 *  where the attempts happened and the dashes span the real gap between one attempt
 *  ending and the next beginning — no arithmetic, nothing inferred.
 *
 *  **Reconstructed.** Runs recorded before that change are not migrated, and they still
 *  have to draw. Those traces carry the backoffs and nothing else, so:
 *
 *      step span = attempt₁ + wait₁ + attempt₂ + wait₂ + … + attemptₙ
 *
 *  the waits are known exactly (`retryInSeconds`), and the work left over — the span
 *  minus every wait — is divided evenly between the attempts. Honest for the failure
 *  this actually happens to (an argument the tool rejects, rejected just as fast every
 *  time), and at worst a plausible ordering for anything else: the bars are in the right
 *  places and the waits, which are the part worth looking at, are exact. The lane is
 *  flagged `estimated`, and the tooltip hedges.
 *
 *  Either way a step with nothing to split — one attempt, or no trace at all — gets a
 *  single bar spanning it, which is the step's own measured span. */
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
  const failedStep = step.status === 'failed';

  const recorded = timedAttempts(step);
  if (recorded.length > 0) {
    return recordedSegments(recorded, step, runStart, totalMs, now);
  }

  const waits = backoffMs(step);
  const entries = attemptEntries(step.trace);
  const totalWait = waits.reduce((sum, ms) => sum + ms, 0);
  const workMs = spanMs - totalWait;

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
      // What the pill counts. On a recorded lane the bars *are* the attempts, so a step
      // cancelled while waiting to retry says "1 try" — the retry it was about to make
      // never happened. Only the reconstruction has to infer a count from the backoffs,
      // and there the retry it waited for did happen.
      attempts: Math.max(
        step.attempt || 1,
        segments.length,
        estimated ? backoffMs(step).length + 1 : 0
      ),
      ran: step.startedAt != null,
      estimated,
    };
  });

  // The policy, not the drawn dashes: a step cancelled while waiting to retry has a
  // backoff it never got to finish, and the footer is still describing the rule it was
  // following. Longest chain any one step declared wins.
  let backoffSeconds: number[] = [];
  for (const step of run.steps) {
    const seconds = backoffMs(step).map((ms) => ms / 1000);
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

/** The gantt footer's second half: the backoff rule this run was actually following.
 *
 *  Phrased as the policy rather than as something that finished happening, because a run
 *  can be cancelled part way through a wait and the rule was still the rule. */
export function retryPolicyLine(backoffSeconds: number[]): string {
  if (backoffSeconds.length === 0) return 'No step needed a second try.';
  const parts = backoffSeconds.map((s) => `${s}s`);
  if (parts.length === 1) return `A retry waits ${parts[0]}.`;
  return `Retries wait ${parts.slice(0, -1).join(', ')}, then ${parts[parts.length - 1]}.`;
}
