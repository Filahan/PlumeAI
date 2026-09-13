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

/** What one completed load left behind. Held as a single value so `loading` can be
 *  derived — `key` is the run it answers, and anything else means "still fetching". */
interface Loaded {
  key: string;
  run: RunWithAutomation | null;
  notFound: boolean;
  error: string | null;
}

const EMPTY: Loaded = { key: '', run: null, notFound: false, error: null };

export interface RunLoad {
  run: RunWithAutomation | null;
  /** True until the first answer arrives — a poll never blanks the page. */
  loading: boolean;
  /** The run id is not one we have. A state, not an error. */
  notFound: boolean;
  /** Anything else that went wrong, in a sentence. */
  error: string | null;
  /** Lay out against this rather than `Date.now()`: it only moves while the run does. */
  now: number;
}

/** Load one run and, while it is queued or running, keep loading it.
 *
 *  The poll stops the moment the run reaches a terminal status and on unmount, and a
 *  failed poll is swallowed — a blip in the network is not a reason to replace a run
 *  that is already on screen with an error.
 */
export function useRun(runId: string): RunLoad {
  const [loaded, setLoaded] = useState<Loaded>(EMPTY);
  const [now, setNow] = useState(() => Date.now());

  const loading = loaded.key !== runId;
  const run = loading ? null : loaded.run;
  // Whether to keep polling is the run's own business, so it is read off the loaded run
  // rather than tracked separately — one source of truth, and no way for the two to
  // disagree about whether the thing is still going.
  const active = run != null && isRunActive(run.status);

  useEffect(() => {
    let cancelled = false;

    activity
      .run(runId)
      .then((detail) => {
        if (!cancelled) setLoaded({ key: runId, run: detail, notFound: false, error: null });
      })
      .catch((reason: unknown) => {
        if (cancelled) return;
        const notFound = reason instanceof ApiError && reason.status === 404;
        setLoaded({
          key: runId,
          run: null,
          notFound,
          error: notFound
            ? null
            : reason instanceof Error
              ? reason.message
              : 'Could not load this run.',
        });
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
          // Keyed, so a poll that lands after the route changed cannot overwrite the run
          // that replaced it.
          if (!cancelled) {
            setLoaded((prev) => (prev.key === runId ? { ...prev, run: detail } : prev));
          }
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

  return { run, loading, notFound: loaded.notFound && !loading, error: loading ? null : loaded.error, now };
}
