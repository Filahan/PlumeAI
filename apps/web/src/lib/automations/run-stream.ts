/** Live run progress: the SSE subscription (with a polling fallback) plus the reducer
 *  that folds each event into a `RunDetail`.
 *
 *  Moved out of the Phase-1 `useAutomations` hook so the zustand store owns run state
 *  and components never subscribe themselves.
 */

import { automations as api, parseSSE } from '@/lib/api';
import type { RunDetail, RunEvent, RunStep } from './types';
import { TERMINAL_RUN_STATUSES } from './types';

const POLL_INTERVAL_MS = 2000;

function isTerminal(status: string): boolean {
  return (TERMINAL_RUN_STATUSES as readonly string[]).includes(status);
}

/** Subscribe to a run's live progress. Tries the SSE stream first; if it errors before
 *  the run reaches a terminal state, falls back to polling `getRun` every 2s and
 *  re-emitting the result as a `snapshot`. Returns an unsubscribe function — always
 *  call it on unmount/navigation or the fetch and the interval leak. */
export function subscribeRun(
  automationId: string,
  runId: string,
  onEvent: (evt: RunEvent) => void
): () => void {
  const controller = new AbortController();
  let stopped = false;
  let pollTimer: ReturnType<typeof setInterval> | null = null;

  const stopPolling = () => {
    if (pollTimer !== null) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  };

  const startPolling = () => {
    if (stopped || pollTimer !== null) return;
    pollTimer = setInterval(() => {
      api
        .getRun(automationId, runId)
        .then((run: RunDetail) => {
          if (stopped) return;
          onEvent({ type: 'snapshot', run });
          if (isTerminal(run.status)) stopPolling();
        })
        .catch(() => {
          // transient — keep polling
        });
    }, POLL_INTERVAL_MS);
  };

  void (async () => {
    // A stream that ends without saying how the run finished tells us nothing — the
    // proxy timed out, the worker was restarted, the connection dropped mid-run. The UI
    // would sit on "running" for ever, so fall back to polling exactly as an error does.
    let sawTerminal = false;
    try {
      const res = await api.runEvents(automationId, runId, controller.signal);
      for await (const evt of parseSSE<RunEvent>(res, controller.signal)) {
        if (stopped) return;
        if (
          evt.type === 'run_finished' ||
          (evt.type === 'snapshot' && isTerminal(evt.run.status))
        ) {
          sawTerminal = true;
        }
        onEvent(evt);
      }
    } catch {
      if (!stopped) startPolling();
      return;
    }
    if (!stopped && !sawTerminal) startPolling();
  })();

  return () => {
    stopped = true;
    controller.abort();
    stopPolling();
  };
}

function patchStep(run: RunDetail, stepId: string, patch: (s: RunStep) => RunStep): RunDetail {
  let changed = false;
  const steps = run.steps.map((s) => {
    if (s.stepId !== stepId) return s;
    changed = true;
    return patch(s);
  });
  return changed ? { ...run, steps } : run;
}

/** Fold one event into the run we're holding. `snapshot` replaces it outright; the
 *  incremental events patch the matching step (or the run) in place. Returns the same
 *  object reference when nothing changed, so zustand subscribers don't re-render. */
export function applyRunEvent(run: RunDetail | null, evt: RunEvent): RunDetail | null {
  if (evt.type === 'snapshot') return evt.run;
  if (!run) return run;

  switch (evt.type) {
    case 'run_started':
      return { ...run, status: evt.status };

    case 'run_finished':
      return { ...run, status: evt.status, error: evt.error ?? run.error };

    case 'step_started':
      return patchStep(run, evt.stepId, (s) => ({
        ...s,
        status: 'running',
        attempt: evt.attempt,
        index: evt.index,
        error: null,
      }));

    case 'step_retry':
      return patchStep(run, evt.stepId, (s) => ({
        ...s,
        attempt: evt.attempt,
        error: evt.error,
        trace: [
          ...s.trace,
          { kind: 'attempt', n: evt.attempt, error: evt.error, retryInSeconds: evt.retryInSeconds },
        ],
      }));

    case 'step_text':
      // AI steps stream their text as the step's (eventual) output.
      return patchStep(run, evt.stepId, (s) => ({
        ...s,
        output: `${typeof s.output === 'string' ? s.output : ''}${evt.delta}`,
      }));

    case 'step_tool_call':
      return patchStep(run, evt.stepId, (s) => ({
        ...s,
        trace: [...s.trace, { kind: 'tool_call', id: evt.id, tool: evt.tool, args: evt.args }],
      }));

    case 'step_tool_result':
      return patchStep(run, evt.stepId, (s) => ({
        ...s,
        trace: [
          ...s.trace,
          { kind: 'tool_result', id: evt.id, tool: evt.tool, ok: evt.ok, result: evt.result },
        ],
      }));

    case 'step_finished':
      return patchStep(run, evt.stepId, (s) => ({
        ...s,
        status: evt.status,
        error: evt.error ?? s.error,
        // `output` rides along only for small payloads; otherwise keep what we have
        // (the streamed text, or nothing until the next snapshot/refetch).
        output: 'output' in evt ? evt.output : (evt.outputPreview ?? s.output),
      }));

    default:
      return run;
  }
}
