'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { activity, automations as automationsApi } from '@/lib/api';
import type { AutomationSummary, RunListItem } from '@/lib/automations/types';
import {
  dayLanes,
  failingStreak,
  rangeStart,
  runTime,
  runsByAutomation,
  type ActivityRange,
  type DayLane,
  type FailingStreak,
} from './derive';

/** One page of the run feed. Large enough that a normal week is one request. */
const PAGE_SIZE = 200;

/** Hard stop on paging: 30 days of a minutely automation is more history than a grid of
 *  20 squares per row can show anyway, and an unbounded loop driven by a server cursor is
 *  how a page hangs. */
const MAX_PAGES = 5;

/** How often the clock the page renders against is re-read. Half a minute, because the
 *  value is rounded down to the minute: every relative label lands within 30s of true. */
const TICK_MS = 30_000;

function currentMinute(): number {
  return Math.floor(Date.now() / 60_000) * 60_000;
}

/** Walk the feed backwards until it reaches past `start`, then keep what is in range.
 *
 *  `before` is a cursor, not a filter — the API hands back the timestamp to resume from,
 *  and a page whose cursor already predates the window is the last one worth asking for. */
async function fetchRange(start: number): Promise<RunListItem[]> {
  const collected: RunListItem[] = [];
  let before: number | undefined;

  for (let page = 0; page < MAX_PAGES; page += 1) {
    const { runs, nextCursor } = await activity.runs({ limit: PAGE_SIZE, before });
    collected.push(...runs);
    if (nextCursor == null || nextCursor <= start) break;
    before = nextCursor;
  }

  return collected.filter((run) => runTime(run) >= start);
}

/** What one completed load left behind. Held as a single value so `loading` can be
 *  derived — `key` is the request it answers, and anything else means "still fetching". */
interface Loaded {
  key: string;
  automations: AutomationSummary[];
  runs: RunListItem[];
  error: string | null;
  runsError: string | null;
}

const EMPTY: Loaded = { key: '', automations: [], runs: [], error: null, runsError: null };

export interface ActivityData {
  automations: AutomationSummary[];
  runs: RunListItem[];
  /** Runs grouped by automation id, newest first. */
  byAutomation: Map<string, RunListItem[]>;
  streak: FailingStreak | null;
  /** Name of the step the streak stops on — resolved from the failed run's detail, and
   *  null while it loads or when the run does not say. */
  streakStepName: string | null;
  lanes: DayLane[];
  loading: boolean;
  /** The automations list failed — there is nothing to draw. */
  error: string | null;
  /** The run feed failed (typically: not deployed yet). The grid still renders, without
   *  squares, rather than taking the page down with it. */
  runsError: string | null;
  reload: () => void;
}

/** Loads everything the Activity section shows and derives the rest.
 *
 *  Two requests, one effect: the automations list (every row of the grid, including the
 *  ones that have never run) and the cross-automation run feed for `range`. They settle
 *  independently — a missing run feed empties the squares, it does not empty the page.
 *
 *  A third, dependent request names the step a failing automation stops on. It only fires
 *  once a streak exists, and only for that one run.
 */
export function useActivity(range: ActivityRange): ActivityData {
  const [nonce, setNonce] = useState(0);
  const [loaded, setLoaded] = useState<Loaded>(EMPTY);
  /** Failed run id → the name of the step it stopped on. */
  const [stepNames, setStepNames] = useState<Record<string, string>>({});
  /** The clock, held in state rather than read at render: "in 13 min" and the day lanes
   *  both depend on now, and a value that changes mid-render is a value you cannot memo. */
  const [nowMinute, setNowMinute] = useState(currentMinute);

  const key = `${range}:${nonce}`;
  const loading = loaded.key !== key;
  const reload = useCallback(() => setNonce((n) => n + 1), []);

  // Relative times and the "now" edge of the timeline would otherwise sit at whatever
  // the last render thought the time was. Setting the same minute twice is a no-op, so
  // this re-renders once a minute, not twice a minute.
  useEffect(() => {
    const handle = window.setInterval(() => setNowMinute(currentMinute()), TICK_MS);
    return () => window.clearInterval(handle);
  }, []);

  useEffect(() => {
    let cancelled = false;
    const start = rangeStart(range, Date.now());

    const load = async () => {
      const [list, feed] = await Promise.allSettled([automationsApi.list(), fetchRange(start)]);
      if (cancelled) return;
      setLoaded({
        key,
        automations: list.status === 'fulfilled' ? list.value : [],
        runs: feed.status === 'fulfilled' ? feed.value : [],
        error:
          list.status === 'fulfilled'
            ? null
            : messageOf(list.reason, 'Could not load your automations.'),
        runsError:
          feed.status === 'fulfilled'
            ? null
            : messageOf(feed.reason, 'Could not load the run history.'),
      });
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [key, range]);

  const { runs, automations } = loaded;
  const byAutomation = useMemo(() => runsByAutomation(runs), [runs]);
  const streak = useMemo(() => failingStreak(runs), [runs]);

  // Recomputed on the tick above: marks move as the day advances, and a running one grows.
  const lanes = useMemo(() => dayLanes(runs, nowMinute), [runs, nowMinute]);

  const streakRunId = streak?.latestRun.id ?? null;
  const streakStepId = streak?.stoppedByStepId ?? null;

  useEffect(() => {
    if (!streakRunId || !streakStepId) return;
    let cancelled = false;
    activity
      .run(streakRunId)
      .then((detail) => {
        const name = detail.steps.find((s) => s.stepId === streakStepId)?.name;
        if (cancelled || !name) return;
        setStepNames((prev) => (prev[streakRunId] === name ? prev : { ...prev, [streakRunId]: name }));
      })
      .catch(() => {
        /* the banner simply stays one line shorter */
      });
    return () => {
      cancelled = true;
    };
  }, [streakRunId, streakStepId]);

  return {
    automations,
    runs,
    byAutomation,
    streak,
    streakStepName: streakRunId ? (stepNames[streakRunId] ?? null) : null,
    lanes,
    loading,
    error: loaded.error,
    runsError: loaded.runsError,
    reload,
  };
}

function messageOf(reason: unknown, fallback: string): string {
  const message = reason instanceof Error ? reason.message : '';
  return message || fallback;
}
