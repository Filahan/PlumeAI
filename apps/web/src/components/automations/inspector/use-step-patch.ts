'use client';

import { useCallback, useEffect, useRef } from 'react';
import { useAutomationsStore } from '@/lib/automations/store';
import type { Operation, StepPatch } from '@/lib/automations/types';

/** Text inputs commit this long after the last keystroke; blur/Enter commits at once. */
const DEBOUNCE_MS = 500;

export interface StepPatcher {
  /** Commit now — for selects, toggles, mode switches and picker choices. */
  patchStep(stepId: string, patch: StepPatch): void;
  /** Commit `DEBOUNCE_MS` after the last call for the same `(stepId, key)` pair.
   *  The newest patch for a key always wins. */
  patchStepDebounced(stepId: string, key: string, patch: StepPatch): void;
  /** Flush a pending debounced patch immediately (blur / Enter). */
  flushStep(stepId: string, key: string): void;
}

/** One write path for every inspector form.
 *
 *  Every patch becomes a single `update_step` operation, so one gesture = one version
 *  (see the store's design-mode contract). Failures land in `current.saveError`, which
 *  the editor shell already renders as a banner under the header — nothing to do here
 *  beyond swallowing the rejection so it doesn't surface as an unhandled promise.
 *
 *  Remember that the backend merges `patch.settings` exactly one level deep: to change
 *  one entry of an action's `input` you must send the whole `input` object. */
export function useStepPatch(): StepPatcher {
  const applyOperations = useAutomationsStore((s) => s.applyOperations);
  const timers = useRef(new Map<string, ReturnType<typeof setTimeout>>());
  const pending = useRef(new Map<string, { stepId: string; patch: StepPatch }>());

  const send = useCallback(
    (stepId: string, patch: StepPatch) => {
      const op: Operation = { op: 'update_step', step_id: stepId, patch };
      void applyOperations([op]).catch(() => {
        // surfaced through `current.saveError`
      });
    },
    [applyOperations]
  );

  const flushKey = useCallback(
    (key: string) => {
      const timer = timers.current.get(key);
      if (timer !== undefined) clearTimeout(timer);
      timers.current.delete(key);
      const entry = pending.current.get(key);
      pending.current.delete(key);
      if (entry) send(entry.stepId, entry.patch);
    },
    [send]
  );

  // Commit whatever is still in flight when the panel closes or the selection moves.
  // (Blur already flushes, so this only catches an unmount that skipped it.)
  useEffect(() => {
    const timerMap = timers.current;
    const pendingMap = pending.current;
    return () => {
      for (const [key, timer] of timerMap) {
        clearTimeout(timer);
        const entry = pendingMap.get(key);
        if (entry) send(entry.stepId, entry.patch);
      }
      timerMap.clear();
      pendingMap.clear();
    };
  }, [send]);

  const patchStep = useCallback(
    (stepId: string, patch: StepPatch) => {
      // An explicit gesture supersedes whatever text is still waiting on its debounce:
      // flush those first so this patch — built on top of their drafts — lands last.
      for (const key of [...timers.current.keys()]) {
        if (key.startsWith(`${stepId}::`)) flushKey(key);
      }
      send(stepId, patch);
    },
    [flushKey, send]
  );

  const patchStepDebounced = useCallback(
    (stepId: string, key: string, patch: StepPatch) => {
      const mapKey = `${stepId}::${key}`;
      pending.current.set(mapKey, { stepId, patch });
      const timer = timers.current.get(mapKey);
      if (timer !== undefined) clearTimeout(timer);
      timers.current.set(
        mapKey,
        setTimeout(() => flushKey(mapKey), DEBOUNCE_MS)
      );
    },
    [flushKey]
  );

  const flushStep = useCallback(
    (stepId: string, key: string) => flushKey(`${stepId}::${key}`),
    [flushKey]
  );

  return { patchStep, patchStepDebounced, flushStep };
}
