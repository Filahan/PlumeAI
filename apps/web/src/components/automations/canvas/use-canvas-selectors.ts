'use client';

/** Narrow store selectors for the canvas nodes.
 *
 *  Every one of these returns a primitive, so a node only re-renders when *its own*
 *  slice changes. That matters during a live run: a `step_text` event arrives many
 *  times a second and must not re-render the whole graph.
 */

import { useAutomationsStore } from '@/lib/automations/store';
import type { RunStepStatus } from '@/lib/automations/types';

export function useTriggerSelected(): boolean {
  return useAutomationsStore((s) => s.current?.selection?.kind === 'trigger');
}

export function useStepSelected(stepId: string): boolean {
  return useAutomationsStore(
    (s) => s.current?.selection?.kind === 'step' && s.current.selection.stepId === stepId
  );
}

/** True when the server flagged an error anywhere under `steps[index]`. Paths come from
 *  the backend validator verbatim (`steps[0].settings.input.query`, …). */
export function useStepHasIssues(index: number): boolean {
  const prefix = `steps[${index}]`;
  return useAutomationsStore(
    (s) => s.current?.issues.some((i) => i.level === 'error' && i.path.startsWith(prefix)) ?? false
  );
}

/** This step's status in the run currently being watched, or null when there is none. */
export function useStepRunStatus(stepId: string): RunStepStatus | null {
  return useAutomationsStore(
    (s) => s.current?.activeRun?.steps.find((r) => r.stepId === stepId)?.status ?? null
  );
}
