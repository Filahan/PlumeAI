'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { activity } from '@/lib/api';
import { runsByAutomation } from '@/lib/activity/derive';
import { isRunActive, type RunListItem, type ScheduleItem } from '@/lib/automations/types';

/** Enough history for the Last result column to say "Failed ×4" rather than "Failed". */
const RUN_PAGE = 200;

/** How often the clock the page renders against is re-read. Half a minute, because every
 *  relative label is rounded to the minute. */
const TICK_MS = 30_000;

function currentMinute(): number {
  return Math.floor(Date.now() / 60_000) * 60_000;
}

/** Failures at the head of one automation's history.
 *
 *  A run still in flight has not failed *yet*, so it is skipped rather than counted —
 *  otherwise the count would drop to zero the moment the next attempt starts. Same rule
 *  as the Runs tab's attention banner. */
function consecutiveFailures(runs: RunListItem[]): number {
  let count = 0;
  for (const run of runs) {
    if (isRunActive(run.status)) continue;
    if (run.status !== 'failed') break;
    count += 1;
  }
  return count;
}

interface Loaded {
  key: string;
  timezone: string;
  schedules: ScheduleItem[];
  runs: RunListItem[];
  error: string | null;
}

const EMPTY: Loaded = { key: '', timezone: '', schedules: [], runs: [], error: null };

export interface SchedulesData {
  /** The workspace zone times are shown in; `''` until the first load lands. */
  timezone: string;
  schedules: ScheduleItem[];
  /** automation id → consecutive failures, for the Last result column. */
  failures: Record<string, number>;
  /** The minute the page is rendering against — passed to every time helper so the
   *  strip, the relative labels and the plan cannot disagree. */
  now: number;
  loading: boolean;
  error: string | null;
  /** A pause/resume is in flight — the switches and the header button go quiet. */
  busy: boolean;
  reload(): void;
  /** `null` means every schedule, which is what "Pause everything" sends. */
  setEnabled(automationIds: string[] | null, enabled: boolean): Promise<void>;
}

/** Loads the schedule board: `/schedules` for the rows, and the run feed for how the
 *  last few attempts went.
 *
 *  The two settle independently — a run feed that is not deployed costs the failure
 *  counts, not the page. Only `/schedules` failing is an error worth showing. */
export function useSchedules(): SchedulesData {
  const [nonce, setNonce] = useState(0);
  const [loaded, setLoaded] = useState<Loaded>(EMPTY);
  const [busy, setBusy] = useState(false);
  const [now, setNow] = useState(currentMinute);

  const key = String(nonce);
  const loading = loaded.key !== key;
  const reload = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    const handle = window.setInterval(() => setNow(currentMinute()), TICK_MS);
    return () => window.clearInterval(handle);
  }, []);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      const [board, feed] = await Promise.allSettled([
        activity.schedules(),
        activity.runs({ limit: RUN_PAGE }),
      ]);
      if (cancelled) return;
      setLoaded({
        key,
        timezone: board.status === 'fulfilled' ? board.value.timezone : '',
        schedules: board.status === 'fulfilled' ? board.value.schedules : [],
        runs: feed.status === 'fulfilled' ? feed.value.runs : [],
        error:
          board.status === 'fulfilled'
            ? null
            : messageOf(board.reason, 'Could not load your schedules.'),
      });
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [key]);

  const failures = useMemo(() => {
    const out: Record<string, number> = {};
    for (const [automationId, bucket] of runsByAutomation(loaded.runs)) {
      const count = consecutiveFailures(bucket);
      if (count > 0) out[automationId] = count;
    }
    return out;
  }, [loaded.runs]);

  const setEnabled = useCallback(
    async (automationIds: string[] | null, enabled: boolean) => {
      setBusy(true);
      try {
        await (enabled
          ? activity.resumeSchedules(automationIds)
          : activity.pauseSchedules(automationIds));
      } finally {
        setBusy(false);
        setNonce((n) => n + 1);
      }
    },
    []
  );

  return {
    timezone: loaded.timezone,
    schedules: loaded.schedules,
    failures,
    now,
    loading,
    error: loaded.error,
    busy,
    reload,
    setEnabled,
  };
}

function messageOf(reason: unknown, fallback: string): string {
  const message = reason instanceof Error ? reason.message : '';
  return message || fallback;
}
