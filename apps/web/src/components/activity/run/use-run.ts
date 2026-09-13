'use client';

import { useEffect, useState } from 'react';
import { activity } from '@/lib/api';
import { ApiError } from '@/lib/api/client';
import { isRunActive, type RunWithAutomation } from '@/lib/automations/types';

/** How often a run still in flight is re-read. Deliberately a poll and not the editor's
 *  SSE stream: this page is a record of what happened, not a console. Two seconds is
 *  fast enough that a step lighting up feels live, and cheap enough that leaving the tab
 *  open all afternoon costs one small request every two seconds. */
const POLL_MS = 2_000;

/** The clock the gantt lays out against while a run is still going, so a running bar
 *  grows between polls instead of sitting still for two seconds at a time. */
const TICK_MS = 500;

export interface RunLoad {
  run: RunWithAutomation | null;
  /** True only on the first load — a poll never blanks the page. */
  loading: boolean;
  /** The run id is not one we have. A state, not an error. */
  notFound: boolean;
  /** Anything else that went wrong, in a sentence. */
  error: string | null;
  /** Re-read against this instead of `Date.now()`: it only moves while the run does. */
  now: number;
}

/** Load one run and, while it is queued or running, keep loading it.
 *
 *  The poll stops the moment the run reaches a terminal status and on unmount, and a
 *  failed poll is swallowed — a blip in the network is not a reason to replace a run
 *  that is already on screen with an error. */
export function useRun(runId: string): RunLoad {
  const [run, setRun] = useState<RunWithAutomation | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());

  // Whether to keep polling is the run's own business, so it is read off the loaded run
  // rather than tracked separately — one source of truth, and no way for the two to
  // disagree about whether the thing is still going.
  const active = run != null && isRunActive(run.status);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setNotFound(false);
    setError(null);
    setRun(null);

    activity
      .run(runId)
      .then((detail) => {
        if (cancelled) return;
        setRun(detail);
        setLoading(false);
      })
      .catch((reason: unknown) => {
        if (cancelled) return;
        if (reason instanceof ApiError && reason.status === 404) setNotFound(true);
        else setError(reason instanceof Error ? reason.message : 'Could not load this run.');
        setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [runId]);

  useEffect(() => {
    if (!active) return;
    let cancelled = false;

    const poll = window.setInterval(() => {
      activity
        .run(runId)
        .then((detail) => {
          if (!cancelled) setRun(detail);
        })
        .catch(() => {
          /* one missed poll changes nothing — the next one will say the same thing */
        });
    }, POLL_MS);
    const tick = window.setInterval(() => setNow(Date.now()), TICK_MS);

    return () => {
      cancelled = true;
      window.clearInterval(poll);
      window.clearInterval(tick);
    };
  }, [active, runId]);

  return { run, loading, notFound, error, now };
}
