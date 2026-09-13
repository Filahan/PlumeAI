'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  AutomationDetail,
  AutomationDocument,
  AutomationSummary,
  DocumentWriteResult,
  RunDetail,
  RunEvent,
  RunSummary,
} from '@/lib/types';
import { automations as api, ApiError, parseSSE } from '@/lib/api';

const POLL_INTERVAL_MS = 2000;

function errorMessage(e: unknown, fallback: string): string {
  if (e instanceof ApiError) return e.message || fallback;
  if (e instanceof Error) return e.message || fallback;
  return fallback;
}

const TERMINAL_RUN_STATUSES = new Set(['succeeded', 'failed', 'cancelled']);

/** Subscribe to a run's live progress. Tries the SSE stream first; if it errors before
 *  the run reaches a terminal state, falls back to polling `getRun` every 2s. Returns an
 *  unsubscribe function. */
function subscribeRun(
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
          if (TERMINAL_RUN_STATUSES.has(run.status)) stopPolling();
        })
        .catch(() => {
          // transient — keep polling
        });
    }, POLL_INTERVAL_MS);
  };

  (async () => {
    try {
      const res = await api.runEvents(automationId, runId, controller.signal);
      for await (const evt of parseSSE<RunEvent>(res, controller.signal)) {
        if (stopped) return;
        onEvent(evt);
      }
    } catch {
      if (!stopped) startPolling();
    }
  })();

  return () => {
    stopped = true;
    controller.abort();
    stopPolling();
  };
}

export function useAutomations() {
  const [automations, setAutomations] = useState<AutomationSummary[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const rows = await api.list();
      setAutomations(rows);
      setError(null);
    } catch (e) {
      setError(errorMessage(e, 'Failed to load automations'));
    } finally {
      setLoaded(true);
    }
  }, []);

  // Initial load — fetches directly (rather than calling `refresh`) so every setState
  // call happens inside the promise callbacks, not synchronously in the effect body.
  useEffect(() => {
    let cancelled = false;
    api
      .list()
      .then((rows) => {
        if (!cancelled) {
          setAutomations(rows);
          setError(null);
        }
      })
      .catch((e) => {
        if (!cancelled) setError(errorMessage(e, 'Failed to load automations'));
      })
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const create = useCallback(async (name: string): Promise<string> => {
    try {
      const detail = await api.create({ name });
      await refresh();
      return detail.id;
    } catch (e) {
      setError(errorMessage(e, 'Failed to create automation'));
      throw e;
    }
  }, [refresh]);

  const remove = useCallback(async (id: string) => {
    try {
      await api.remove(id);
      setAutomations((prev) => prev.filter((a) => a.id !== id));
    } catch (e) {
      setError(errorMessage(e, 'Failed to delete automation'));
      throw e;
    }
  }, []);

  const setEnabled = useCallback(async (id: string, enabled: boolean) => {
    try {
      const detail = await api.patch(id, { enabled });
      setAutomations((prev) =>
        prev.map((a) => (a.id === id ? { ...a, enabled: detail.enabled } : a))
      );
    } catch (e) {
      setError(errorMessage(e, 'Failed to update automation'));
      throw e;
    }
  }, []);

  const rename = useCallback(async (id: string, name: string) => {
    try {
      const detail = await api.patch(id, { name });
      setAutomations((prev) => prev.map((a) => (a.id === id ? { ...a, name: detail.name } : a)));
      return detail;
    } catch (e) {
      setError(errorMessage(e, 'Failed to rename automation'));
      throw e;
    }
  }, []);

  const getDetail = useCallback(async (id: string): Promise<AutomationDetail> => {
    try {
      return await api.get(id);
    } catch (e) {
      setError(errorMessage(e, 'Failed to load automation'));
      throw e;
    }
  }, []);

  const putDocument = useCallback(
    async (id: string, document: AutomationDocument): Promise<DocumentWriteResult> => {
      // Deliberately does NOT swallow — a 422 here carries `issues` the caller needs to
      // render, so let it throw and let the caller decide what to show.
      return api.put(id, document);
    },
    []
  );

  const startRun = useCallback(async (id: string): Promise<string> => {
    try {
      const { runId } = await api.startRun(id, 'manual');
      await refresh();
      return runId;
    } catch (e) {
      setError(errorMessage(e, 'Failed to start run'));
      throw e;
    }
  }, [refresh]);

  const cancelRun = useCallback(async (id: string, runId: string) => {
    try {
      return await api.cancelRun(id, runId);
    } catch (e) {
      setError(errorMessage(e, 'Failed to cancel run'));
      throw e;
    }
  }, []);

  const listRuns = useCallback(async (id: string): Promise<RunSummary[]> => {
    try {
      return await api.listRuns(id);
    } catch (e) {
      setError(errorMessage(e, 'Failed to load runs'));
      throw e;
    }
  }, []);

  const getRun = useCallback(async (id: string, runId: string): Promise<RunDetail> => {
    try {
      return await api.getRun(id, runId);
    } catch (e) {
      setError(errorMessage(e, 'Failed to load run'));
      throw e;
    }
  }, []);

  const clearError = useCallback(() => setError(null), []);

  return {
    automations,
    loaded,
    error,
    clearError,
    refresh,
    create,
    remove,
    setEnabled,
    rename,
    getDetail,
    putDocument,
    startRun,
    cancelRun,
    listRuns,
    getRun,
    subscribeRun,
  };
}
