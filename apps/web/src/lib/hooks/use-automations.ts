'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { Task, Provider, TaskSchedule, TranscriptStep, ToolStep, InterviewMessage, TaskRun } from '@/lib/types';
import { automations, parseSSE } from '@/lib/api';

const listTasksAction = automations.list;
const createTaskAction = automations.create;
const updateTaskAction = automations.update;
const deleteTaskAction = automations.delete;

function newId(): string {
  return crypto.randomUUID();
}

type RunEvent =
  | { type: 'text'; delta: string }
  | { type: 'tool_call'; id: string; tool: string; args: string }
  | { type: 'tool_result'; id: string; tool: string; ok: boolean; result: string }
  | { type: 'final'; text: string }
  | { type: 'error'; message: string }
  | { type: 'done'; status: Task['status'] };

export function useAutomations() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [chatBusy, setChatBusy] = useState<Record<string, boolean>>({});
  const [chatError, setChatError] = useState<Record<string, string | undefined>>({});
  const controllers = useRef<Map<string, AbortController>>(new Map());

  useEffect(() => {
    let cancelled = false;
    listTasksAction()
      .then((rows) => {
        if (!cancelled) setTasks(rows);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const patchTask = useCallback((id: string, patch: Partial<Task>) => {
    setTasks((prev) => prev.map((t) => (t.id === id ? { ...t, ...patch, updatedAt: Date.now() } : t)));
  }, []);

  // Create + persist a task (so the server can load it by id), then return its id.
  const createTask = useCallback(
    async (prompt: string, schedule: TaskSchedule, provider: Provider, model: string): Promise<string> => {
      const id = newId();
      const now = Date.now();
      const task: Task = { id, prompt, messages: [], schedule, status: 'idle', transcript: [], runs: [], provider, model, createdAt: now, updatedAt: now, title: undefined };
      setTasks((prev) => [task, ...prev]);
      await createTaskAction(id, prompt, schedule, provider, model).catch(() => {});
      return id;
    },
    []
  );

  // Send a user message to the interviewer. Errors are surfaced through chatError[id]
  // rather than thrown, so callers don't need try/catch and the indicator survives
  // the TaskComposer→InterviewChat swap on the first message.
  const chat = useCallback(async (id: string, message: string): Promise<void> => {
    const userMsg: InterviewMessage = { role: 'user', content: message };
    setChatBusy((b) => ({ ...b, [id]: true }));
    setChatError((e) => ({ ...e, [id]: undefined }));
    setTasks((prev) =>
      prev.map((t) => (t.id === id ? { ...t, messages: [...t.messages, userMsg], updatedAt: Date.now() } : t))
    );
    try {
      const data = await automations.chat(id, message);
      setTasks((prev) =>
        prev.map((t) => {
          if (t.id !== id) return t;
          const newAsst: InterviewMessage =
            data.finalized
              ? { role: 'assistant', content: 'Skill ready.' }
              : { role: 'assistant', content: data.question ?? '', ...(data.options ? { options: data.options } : {}) };
          return {
            ...t,
            messages: [...t.messages, newAsst],
            ...(data.finalized && data.skill ? { prompt: data.skill } : {}),
            ...(data.title ? { title: data.title } : {}),
            updatedAt: Date.now(),
          };
        })
      );
    } catch (e) {
      // Roll back the optimistic user message — the server didn't persist it.
      setTasks((prev) =>
        prev.map((t) =>
          t.id === id ? { ...t, messages: t.messages.slice(0, -1), updatedAt: Date.now() } : t
        )
      );
      setChatError((errs) => ({ ...errs, [id]: e instanceof Error ? e.message : 'Chat failed' }));
    } finally {
      setChatBusy((b) => ({ ...b, [id]: false }));
    }
  }, []);

  const clearChatError = useCallback((id: string) => {
    setChatError((e) => ({ ...e, [id]: undefined }));
  }, []);

  const updateTask = useCallback(
    (id: string, patch: { prompt?: string; schedule?: TaskSchedule; provider?: Provider; model?: string }) => {
      patchTask(id, patch);
      updateTaskAction(id, patch).catch(() => {});
    },
    [patchTask]
  );

  // Execute a task via the server-side agent loop (SSE). Tools + secrets run server-side.
  const runTask = useCallback(
    async (id: string): Promise<void> => {
      const controller = new AbortController();
      controllers.current.set(id, controller);
      const runStartedAt = Date.now();
      patchTask(id, { status: 'running', output: '', transcript: [], error: undefined });

      let assistantBuf = '';
      const transcript: TranscriptStep[] = [];
      const idToIndex = new Map<string, number>();

      try {
        const res = await automations.runStream(id, controller.signal);

        for await (const evt of parseSSE<RunEvent>(res, controller.signal)) {
          if (evt.type === 'text') {
              assistantBuf += evt.delta;
              patchTask(id, { output: assistantBuf });
            } else if (evt.type === 'tool_call') {
              if (assistantBuf) {
                transcript.push({ kind: 'assistant', text: assistantBuf });
                assistantBuf = '';
              }
              transcript.push({ kind: 'tool', tool: evt.tool, args: evt.args, result: '', ok: true });
              idToIndex.set(evt.id, transcript.length - 1);
              patchTask(id, { transcript: [...transcript], output: '' });
            } else if (evt.type === 'tool_result') {
              const idx = idToIndex.get(evt.id);
              if (idx !== undefined) {
                transcript[idx] = { ...(transcript[idx] as ToolStep), result: evt.result, ok: evt.ok };
                patchTask(id, { transcript: [...transcript] });
              }
            } else if (evt.type === 'final') {
              assistantBuf = evt.text;
              patchTask(id, { output: evt.text });
            } else if (evt.type === 'error') {
              patchTask(id, { error: evt.message });
            } else if (evt.type === 'done') {
              // Append a TaskRun entry optimistically. Server has already persisted it; this
              // just keeps the UI in sync without a re-fetch. Use functional setTasks to
              // avoid stale-closure reads of `tasks`.
              const endedAt = Date.now();
              const newRun: TaskRun = {
                status: (evt.status === 'failed' || evt.status === 'cancelled' ? evt.status : 'succeeded'),
                startedAt: runStartedAt,
                endedAt,
                durationMs: endedAt - runStartedAt,
              };
              setTasks((prev) =>
                prev.map((t) =>
                  t.id === id ? { ...t, runs: [...(t.runs ?? []), newRun].slice(-30) } : t
                )
              );
              const last = transcript[transcript.length - 1];
              if (assistantBuf && (!last || last.kind === 'tool')) {
                transcript.push({ kind: 'assistant', text: assistantBuf });
              }
              patchTask(id, { status: evt.status, transcript: [...transcript], output: assistantBuf });
            }
        }
      } catch (e) {
        if (controller.signal.aborted) {
          patchTask(id, { status: 'cancelled' });
        } else {
          const message = e instanceof Error ? e.message : 'Run failed';
          patchTask(id, { status: 'failed', error: message });
        }
      } finally {
        controllers.current.delete(id);
      }
    },
    [patchTask]
  );

  const cancel = useCallback((id: string) => {
    controllers.current.get(id)?.abort();
  }, []);

  const deleteTask = useCallback((id: string) => {
    controllers.current.get(id)?.abort();
    setTasks((prev) => prev.filter((t) => t.id !== id));
    deleteTaskAction(id).catch(() => {});
  }, []);

  return { tasks, loaded, chatBusy, chatError, createTask, chat, clearChatError, updateTask, runTask, cancel, deleteTask };
}
