'use client';

/** The automation editor's single source of truth (zustand).
 *
 *  Two write paths, on purpose:
 *
 *  1. **Design mode** (canvas + inspector) persists *per gesture* through
 *     `applyOperations` — one user gesture = one operation = one version. There is no
 *     Save button; `savedDocument` is replaced by whatever the server echoes back.
 *  2. **JSON mode** edits `document` locally via `setDocument` (which marks the draft
 *     dirty and debounce-validates it) and persists explicitly with `saveDocument`
 *     (`PUT`, the only write that can reject a document with 422 + issues).
 *
 *  Components read state through the selector hooks at the bottom and never keep their
 *  own copy of it. The live run subscription is owned here too, so navigating away
 *  (`close`) or switching runs always tears the previous stream down.
 */

import { useEffect } from 'react';
import { create } from 'zustand';
import { ApiError, automations as api, tools as toolsApi } from '@/lib/api';
import { applyRunEvent, subscribeRun } from './run-stream';
import type {
  AssistantMessage,
  AutomationDocument,
  AutomationSummary,
  Catalog,
  LastRunPayload,
  Operation,
  RunDetail,
  RunSummary,
  ValidationIssue,
} from './types';
import { documentsEqual, isRunActive } from './types';

const VALIDATE_DEBOUNCE_MS = 400;
/** How long the canvas rings the steps an assistant turn touched. */
const HIGHLIGHT_MS = 2000;

export type EditorMode = 'design' | 'json';

/** What the inspector is pointed at. `null` = nothing selected. */
export type Selection = { kind: 'trigger' } | { kind: 'step'; stepId: string } | null;

/** The builder assistant's drawer state.
 *
 *  Top-level rather than part of `current`, because `pendingFirstMessage` is written by
 *  the home page *before* the editor (and therefore `current`) exists. */
export interface AssistantSlice {
  /** The transcript as the server has it, oldest first. */
  messages: AssistantMessage[];
  sending: boolean;
  /** Request-level failure — no API key for the provider, or the provider itself down.
   *  A turn the assistant got wrong is *not* this: it rides along in the transcript as
   *  the entry's own `error`. */
  error: string | null;
  /** What the last turn applied, one human sentence per change. */
  lastSummary: string[];
  /** Version to restore for "Undo" — the document as it was before the last turn, or
   *  null when that turn changed nothing (or has already been undone). */
  lastVersionBefore: number | null;
  /** Typed on the home page before it navigates; the editor sends it as the first
   *  message once `open(id)` has resolved. */
  pendingFirstMessage: string | null;
}

const EMPTY_ASSISTANT: AssistantSlice = {
  messages: [],
  sending: false,
  error: null,
  lastSummary: [],
  lastVersionBefore: null,
  pendingFirstMessage: null,
};

export interface CurrentAutomation {
  id: string;
  name: string;
  /** The draft being edited. Equals `savedDocument` unless the JSON editor is dirty. */
  document: AutomationDocument;
  /** Last document the server acknowledged. */
  savedDocument: AutomationDocument;
  versionNumber: number;
  issues: ValidationIssue[];
  enabled: boolean;
  nextRunAt: number | null;
  lastRun: LastRunPayload | null;

  dirty: boolean;
  saving: boolean;
  /** One short sentence for the banner. */
  saveError: string | null;
  /** The server's own wording behind the banner's "Details" disclosure. */
  saveErrorDetail: string | null;
  /** Per-field problems the *rejected write* carried (`operations.0.set_trigger`, …).
   *  They describe the request, not the document, so they live next to the banner
   *  instead of in `issues` — which the canvas and the inspector read. */
  saveErrorIssues: ValidationIssue[];

  selection: Selection;
  mode: EditorMode;
  /** Set when `setMode` would have to throw away an unsaved JSON draft: the header asks
   *  first and the switch only happens through `confirmModeSwitch`. */
  pendingModeSwitch: EditorMode | null;
  inspectorOpen: boolean;
  runPanelOpen: boolean;
  assistantOpen: boolean;

  runs: RunSummary[];
  activeRunId: string | null;
  activeRun: RunDetail | null;
}

interface AutomationsState {
  list: AutomationSummary[];
  listLoaded: boolean;
  listError: string | null;

  catalog: Catalog | null;

  current: CurrentAutomation | null;
  /** Set while `open(id)` is in flight — `current` is null until the detail lands. */
  currentLoading: boolean;
  currentError: string | null;

  /** The canvas step picker. `index` is where the chosen step will be inserted; it is
   *  set by whichever "+" was clicked (an edge, the trailing card, the empty state). */
  stepPicker: { open: boolean; index: number | null };

  assistant: AssistantSlice;
  /** Steps an assistant turn just added or rewrote, cleared by a timeout. The canvas
   *  rings them so the user can see what the drawer is talking about. */
  recentlyChangedStepIds: string[];
}

interface AutomationsActions {
  loadList(): Promise<void>;
  loadCatalog(): Promise<void>;

  open(id: string): Promise<void>;
  close(): void;

  create(name?: string): Promise<string>;
  remove(id: string): Promise<void>;
  setEnabled(id: string, enabled: boolean): Promise<void>;
  rename(name: string): Promise<void>;

  setDocument(doc: AutomationDocument): void;
  applyOperations(ops: Operation[]): Promise<void>;
  saveDocument(): Promise<void>;
  validateDraft(): void;

  select(selection: Selection): void;
  setMode(mode: EditorMode): void;
  confirmModeSwitch(): void;
  cancelModeSwitch(): void;
  setInspectorOpen(open: boolean): void;
  toggleInspector(): void;
  setRunPanelOpen(open: boolean): void;
  toggleRunPanel(): void;
  setAssistantOpen(open: boolean): void;
  toggleAssistant(): void;

  startRun(trigger?: 'manual' | 'test'): Promise<void>;
  cancelRun(): Promise<void>;
  selectRun(runId: string): Promise<void>;
  refreshRuns(): Promise<void>;

  openStepPicker(index: number): void;
  closeStepPicker(): void;

  sendAssistantMessage(text: string): Promise<void>;
  undoAssistant(): Promise<void>;
  clearAssistant(): Promise<void>;
  /** Queue the home page's first message; consumed once the editor has opened. */
  setAssistantFirstMessage(text: string): void;
  consumeAssistantFirstMessage(): string | null;
}

type Store = AutomationsState & AutomationsActions;

// Module-scoped (not state): imperative handles that must never trigger a re-render.
let runUnsubscribe: (() => void) | null = null;
let validateTimer: ReturnType<typeof setTimeout> | null = null;
let catalogPromise: Promise<void> | null = null;
/** Guards against a stale `open()`/`selectRun()` response overwriting a newer one. */
let openToken = 0;
/** Document writes are serialized: two overlapping `POST /operations` calls would each
 *  echo a whole document back, and whichever answered last would win — which is not
 *  necessarily the newest edit. Everything chains here instead. */
let writeQueue: Promise<unknown> = Promise.resolve();
/** Stamp handed to each write as it is *issued*. A response is adopted only while its
 *  stamp is still the newest, so a late echo can never revert a newer edit. */
let writeStamp = 0;

/** Clears `recentlyChangedStepIds` two seconds after a turn lit it up. */
let highlightTimer: ReturnType<typeof setTimeout> | null = null;

function enqueueWrite<T>(task: () => Promise<T>): Promise<T> {
  // `then(task, task)` so one rejected write does not poison the queue behind it.
  const run = writeQueue.then(task, task);
  writeQueue = run.then(
    () => undefined,
    () => undefined
  );
  return run;
}

function cancelHighlight(): void {
  if (highlightTimer !== null) {
    clearTimeout(highlightTimer);
    highlightTimer = null;
  }
}

/** Ids of the steps `after` added or rewrote relative to `before` — a moved step is not
 *  a change, so the comparison is by id rather than by position. */
function changedStepIds(before: AutomationDocument, after: AutomationDocument): string[] {
  const previous = new Map(before.steps.map((step) => [step.id, step]));
  return after.steps
    .filter((step) => {
      const was = previous.get(step.id);
      return was === undefined || !documentsEqual(was, step);
    })
    .map((step) => step.id);
}

function stopRunStream(): void {
  if (runUnsubscribe) {
    runUnsubscribe();
    runUnsubscribe = null;
  }
}

function cancelValidate(): void {
  if (validateTimer !== null) {
    clearTimeout(validateTimer);
    validateTimer = null;
  }
}

function errorMessage(e: unknown, fallback: string): string {
  if (e instanceof ApiError) return e.message || fallback;
  if (e instanceof Error) return e.message || fallback;
  return fallback;
}

/** Issues a rejected write raised **about the document** — the `extra.issues` of a 422
 *  from `PUT /automations/{id}`, already in the shape `IssuesList` renders. Only these
 *  may replace `current.issues`. */
function documentIssuesFromError(e: unknown): ValidationIssue[] | null {
  if (!(e instanceof ApiError)) return null;
  const extra = e.problem?.extra as { issues?: unknown } | undefined;
  if (!Array.isArray(extra?.issues) || extra.issues.length === 0) return null;
  return extra.issues as ValidationIssue[];
}

/** Issues a rejected write raised **about the request** — FastAPI's `errors[]`, whose
 *  paths point into the payload (`operations.0.set_trigger`) and say nothing about the
 *  document. They belong to the banner, not to `current.issues`. */
function requestIssuesFromError(e: unknown): ValidationIssue[] {
  if (!(e instanceof ApiError)) return [];
  return documentIssuesFromError(e) ? [] : e.issues;
}

/** The server's raw wording, kept out of the banner itself — a Pydantic `detail` is
 *  often several lines long. */
function errorDetail(e: unknown): string | null {
  if (e instanceof ApiError) return e.detail || e.message || null;
  if (e instanceof Error) return e.message || null;
  return null;
}

export const useAutomationsStore = create<Store>((set, get) => {
  /** Patch `current` only when it is still the automation the caller was acting on. */
  const patchCurrent = (id: string, patch: Partial<CurrentAutomation>): void => {
    set((s) => (s.current && s.current.id === id ? { current: { ...s.current, ...patch } } : s));
  };

  /** Ring the given steps on the canvas for a moment, then stop. */
  const flashSteps = (stepIds: string[]): void => {
    cancelHighlight();
    if (stepIds.length === 0) {
      set({ recentlyChangedStepIds: [] });
      return;
    }
    set({ recentlyChangedStepIds: stepIds });
    highlightTimer = setTimeout(() => {
      highlightTimer = null;
      set({ recentlyChangedStepIds: [] });
    }, HIGHLIGHT_MS);
  };

  const subscribe = (automationId: string, runId: string): void => {
    stopRunStream();
    runUnsubscribe = subscribeRun(automationId, runId, (evt) => {
      set((s) => {
        const cur = s.current;
        if (!cur || cur.id !== automationId || cur.activeRunId !== runId) return s;
        const nextRun = applyRunEvent(cur.activeRun, evt);
        const runs =
          nextRun && nextRun.status !== cur.activeRun?.status
            ? cur.runs.map((r) =>
                r.id === runId
                  ? { ...r, status: nextRun.status, error: nextRun.error, endedAt: nextRun.endedAt }
                  : r
              )
            : cur.runs;
        if (nextRun === cur.activeRun && runs === cur.runs) return s;
        return { current: { ...cur, activeRun: nextRun, runs } };
      });
      // A polled snapshot is the only thing that arrives once the SSE stream has been
      // given up on, so a terminal status there has to close the run out too —
      // otherwise the history and the sidebar keep the run's last in-flight state.
      const finished =
        evt.type === 'run_finished' ||
        (evt.type === 'snapshot' && !isRunActive(evt.run.status));
      if (finished) {
        stopRunStream();
        void get().refreshRuns();
        void get().loadList();
      }
    });
  };

  return {
    list: [],
    listLoaded: false,
    listError: null,
    catalog: null,
    current: null,
    currentLoading: false,
    currentError: null,
    stepPicker: { open: false, index: null },
    assistant: EMPTY_ASSISTANT,
    recentlyChangedStepIds: [],

    // ── list ──────────────────────────────────────────────────────────────────────

    async loadList() {
      try {
        const rows = await api.list();
        set({ list: rows, listError: null, listLoaded: true });
      } catch (e) {
        set({ listError: errorMessage(e, 'Failed to load automations'), listLoaded: true });
      }
    },

    async loadCatalog() {
      if (get().catalog) return;
      if (!catalogPromise) {
        catalogPromise = toolsApi
          .catalog()
          .then((catalog) => {
            set({ catalog });
          })
          .catch(() => {
            // A missing catalog degrades labels, never blocks editing — stay quiet and
            // let the next caller retry.
          })
          .finally(() => {
            catalogPromise = null;
          });
      }
      return catalogPromise;
    },

    // ── open / close ──────────────────────────────────────────────────────────────

    async open(id) {
      stopRunStream();
      cancelValidate();
      cancelHighlight();
      const token = ++openToken;
      set({ currentLoading: true, currentError: null });
      try {
        const [detail, runs] = await Promise.all([api.get(id), api.listRuns(id)]);
        if (token !== openToken) return;
        const latest = runs[0] ?? null;
        set({
          currentLoading: false,
          currentError: null,
          current: {
            id: detail.id,
            name: detail.name,
            document: detail.document,
            savedDocument: detail.document,
            versionNumber: detail.versionNumber,
            issues: detail.issues,
            enabled: detail.enabled,
            nextRunAt: detail.nextRunAt,
            lastRun: detail.lastRun,
            dirty: false,
            saving: false,
            saveError: null,
            saveErrorDetail: null,
            saveErrorIssues: [],
            selection: null,
            mode: 'design',
            pendingModeSwitch: null,
            inspectorOpen: true,
            runPanelOpen: false,
            // Coming from the home page's "describe it" box, the drawer is the point.
            assistantOpen: get().assistant.pendingFirstMessage !== null,
            runs,
            activeRunId: latest?.id ?? null,
            activeRun: null,
          },
          recentlyChangedStepIds: [],
          assistant: {
            ...EMPTY_ASSISTANT,
            messages: detail.assistantMessages,
            pendingFirstMessage: get().assistant.pendingFirstMessage,
          },
        });
        if (latest) void get().selectRun(latest.id);
      } catch (e) {
        if (token !== openToken) return;
        set({
          currentLoading: false,
          currentError: errorMessage(e, 'Failed to load automation'),
          current: null,
        });
      }
    },

    close() {
      stopRunStream();
      cancelValidate();
      cancelHighlight();
      openToken += 1;
      // `pendingFirstMessage` survives: the home page sets it before it navigates, and
      // the editor it is meant for has not mounted yet.
      set((state) => ({
        current: null,
        currentLoading: false,
        currentError: null,
        recentlyChangedStepIds: [],
        assistant: { ...EMPTY_ASSISTANT, pendingFirstMessage: state.assistant.pendingFirstMessage },
      }));
    },

    // ── list-level mutations ──────────────────────────────────────────────────────

    async create(name) {
      const detail = await api.create(name ? { name } : undefined);
      await get().loadList();
      return detail.id;
    },

    async remove(id) {
      try {
        await api.remove(id);
      } catch (e) {
        set({ listError: errorMessage(e, 'Failed to delete automation') });
        throw e;
      }
      set((s) => ({ list: s.list.filter((a) => a.id !== id) }));
      if (get().current?.id === id) get().close();
    },

    async setEnabled(id, enabled) {
      // Optimistic — the switch should not lag behind the click.
      set((s) => ({
        list: s.list.map((a) => (a.id === id ? { ...a, enabled } : a)),
        current: s.current && s.current.id === id ? { ...s.current, enabled } : s.current,
      }));
      try {
        const detail = await api.patch(id, { enabled });
        set((s) => ({
          list: s.list.map((a) =>
            a.id === id ? { ...a, enabled: detail.enabled, nextRunAt: detail.nextRunAt } : a
          ),
          current:
            s.current && s.current.id === id
              ? { ...s.current, enabled: detail.enabled, nextRunAt: detail.nextRunAt }
              : s.current,
        }));
      } catch (e) {
        set((s) => ({
          list: s.list.map((a) => (a.id === id ? { ...a, enabled: !enabled } : a)),
          current:
            s.current && s.current.id === id
              ? { ...s.current, enabled: !enabled }
              : s.current,
          listError: errorMessage(e, 'Failed to update automation'),
        }));
      }
    },

    async rename(name) {
      const cur = get().current;
      const trimmed = name.trim();
      if (!cur || !trimmed || trimmed === cur.name) return;
      const id = cur.id;
      const detail = await api.patch(id, { name: trimmed });
      // PATCH renames the automation *and* its document, so mirror the new name into
      // both copies of the document rather than marking the draft dirty.
      set((s) => ({
        list: s.list.map((a) => (a.id === id ? { ...a, name: detail.name } : a)),
        current:
          s.current && s.current.id === id
            ? {
                ...s.current,
                name: detail.name,
                document: { ...s.current.document, name: detail.name },
                savedDocument: { ...s.current.savedDocument, name: detail.name },
                versionNumber: detail.versionNumber,
              }
            : s.current,
      }));
    },

    // ── document writes ───────────────────────────────────────────────────────────

    setDocument(doc) {
      const cur = get().current;
      if (!cur) return;
      set({
        current: {
          ...cur,
          document: doc,
          dirty: !documentsEqual(doc, cur.savedDocument),
          saveError: null,
          saveErrorDetail: null,
          saveErrorIssues: [],
        },
      });
      get().validateDraft();
    },

    validateDraft() {
      cancelValidate();
      validateTimer = setTimeout(() => {
        validateTimer = null;
        const cur = get().current;
        if (!cur) return;
        const { id, document } = cur;
        api
          .validate(document)
          .then((res) => {
            // Only apply if the draft hasn't moved on since the request went out.
            const latest = get().current;
            if (!latest || latest.id !== id || !documentsEqual(latest.document, document)) return;
            patchCurrent(id, { issues: res.issues });
          })
          .catch(() => {
            // Validation is advisory — a failed round trip leaves the issues as they were.
          });
      }, VALIDATE_DEBOUNCE_MS);
    },

    async applyOperations(ops) {
      const cur = get().current;
      if (!cur || ops.length === 0) return;
      if (cur.dirty) {
        // A design-mode operation is computed against `savedDocument`; applying it on
        // top of an unsaved JSON draft would silently throw that draft away.
        console.warn('applyOperations ignored: the JSON draft has unsaved changes');
        return;
      }
      const id = cur.id;
      const stamp = ++writeStamp;
      patchCurrent(id, {
        saving: true,
        saveError: null,
        saveErrorDetail: null,
        saveErrorIssues: [],
      });
      return enqueueWrite(async () => {
        try {
          const res = await api.operations(id, ops);
          // A newer write was issued while this one was in flight — let its echo land.
          if (stamp !== writeStamp) return;
          cancelValidate();
          patchCurrent(id, {
            document: res.document,
            savedDocument: res.document,
            issues: res.issues,
            versionNumber: res.versionNumber,
            dirty: false,
            saving: false,
            saveError: null,
            saveErrorDetail: null,
            saveErrorIssues: [],
          });
          void get().loadList();
        } catch (e) {
          if (stamp === writeStamp) {
            // Only document issues may replace `issues`; request-shaped ones would put
            // payload paths in front of the canvas and the inspector.
            const issues = documentIssuesFromError(e);
            patchCurrent(id, {
              saving: false,
              saveError: "That change wasn't accepted.",
              saveErrorDetail: errorDetail(e),
              saveErrorIssues: requestIssuesFromError(e),
              ...(issues ? { issues } : {}),
            });
          }
          throw e;
        }
      });
    },

    async saveDocument() {
      const cur = get().current;
      if (!cur) return;
      const { id, document } = cur;
      const stamp = ++writeStamp;
      patchCurrent(id, {
        saving: true,
        saveError: null,
        saveErrorDetail: null,
        saveErrorIssues: [],
      });
      return enqueueWrite(async () => {
        try {
          const res = await api.put(id, document);
          if (stamp !== writeStamp) return;
          cancelValidate();
          patchCurrent(id, {
            document: res.document,
            savedDocument: res.document,
            issues: res.issues,
            versionNumber: res.versionNumber,
            dirty: false,
            saving: false,
            saveError: null,
            saveErrorDetail: null,
            saveErrorIssues: [],
          });
          void get().loadList();
        } catch (e) {
          if (stamp !== writeStamp) return;
          // 422 → keep the draft (and its dirty flag) so the user can fix it in place.
          const issues = documentIssuesFromError(e);
          patchCurrent(id, {
            saving: false,
            saveError: "That change wasn't accepted.",
            saveErrorDetail: errorDetail(e),
            saveErrorIssues: requestIssuesFromError(e),
            ...(issues ? { issues } : {}),
          });
        }
      });
    },

    // ── editor chrome ─────────────────────────────────────────────────────────────

    select(selection) {
      set((s) =>
        s.current
          ? { current: { ...s.current, selection, inspectorOpen: selection ? true : s.current.inspectorOpen } }
          : s
      );
    },

    setMode(mode) {
      const cur = get().current;
      if (!cur || mode === cur.mode) return;
      // Leaving JSON mode with an unsaved draft means losing it. Ask in the header
      // rather than discarding it (or, worse, carrying it into design mode where the
      // next operation would be computed against a document the server never saw).
      if (mode === 'design' && cur.dirty) {
        patchCurrent(cur.id, { pendingModeSwitch: mode });
        return;
      }
      patchCurrent(cur.id, { mode, pendingModeSwitch: null });
    },

    confirmModeSwitch() {
      const cur = get().current;
      if (!cur?.pendingModeSwitch) return;
      cancelValidate();
      patchCurrent(cur.id, {
        mode: cur.pendingModeSwitch,
        document: cur.savedDocument,
        dirty: false,
        saveError: null,
        saveErrorDetail: null,
        saveErrorIssues: [],
        pendingModeSwitch: null,
      });
      // The issues on screen were computed against the draft we just dropped.
      get().validateDraft();
    },

    cancelModeSwitch() {
      const cur = get().current;
      if (!cur) return;
      patchCurrent(cur.id, { pendingModeSwitch: null });
    },

    setInspectorOpen(open) {
      set((s) => (s.current ? { current: { ...s.current, inspectorOpen: open } } : s));
    },

    toggleInspector() {
      set((s) =>
        s.current ? { current: { ...s.current, inspectorOpen: !s.current.inspectorOpen } } : s
      );
    },

    setRunPanelOpen(open) {
      set((s) => (s.current ? { current: { ...s.current, runPanelOpen: open } } : s));
    },

    toggleRunPanel() {
      set((s) =>
        s.current ? { current: { ...s.current, runPanelOpen: !s.current.runPanelOpen } } : s
      );
    },

    setAssistantOpen(open) {
      set((s) => (s.current ? { current: { ...s.current, assistantOpen: open } } : s));
    },

    toggleAssistant() {
      set((s) =>
        s.current ? { current: { ...s.current, assistantOpen: !s.current.assistantOpen } } : s
      );
    },

    // ── runs ──────────────────────────────────────────────────────────────────────

    async startRun(trigger = 'manual') {
      const cur = get().current;
      if (!cur) return;
      const id = cur.id;
      try {
        const { runId } = await api.startRun(id, trigger);
        const runs = await api.listRuns(id);
        if (get().current?.id !== id) return;
        patchCurrent(id, { runs, activeRunId: runId, activeRun: null, runPanelOpen: true });
        subscribe(id, runId);
        // Pull the initial detail too: the SSE snapshot normally beats this, and
        // `applyRunEvent` keeps whichever arrives last.
        void get().selectRun(runId);
        void get().loadList();
      } catch (e) {
        patchCurrent(
          id,
          e instanceof ApiError && e.status === 409
            ? {
                saveError: 'A run is already in progress.',
                saveErrorDetail: null,
                saveErrorIssues: [],
              }
            : {
                saveError: errorMessage(e, 'Failed to start run'),
                saveErrorDetail: errorDetail(e),
                saveErrorIssues: [],
              }
        );
        throw e;
      }
    },

    /** Cancels whichever run is actually live — not `activeRunId`, which is just the
     *  row the run panel happens to be showing (the newest run on open, or whatever the
     *  user last clicked). Those are the same run most of the time and confusingly
     *  different exactly when it matters. */
    async cancelRun() {
      const cur = get().current;
      if (!cur) return;
      const target = cur.runs.find((r) => isRunActive(r.status));
      if (!target) return;
      const { id } = cur;
      const runId = target.id;
      try {
        await api.cancelRun(id, runId);
      } catch (e) {
        patchCurrent(id, {
          saveError: errorMessage(e, 'Failed to cancel run'),
          saveErrorDetail: errorDetail(e),
          saveErrorIssues: [],
        });
        return;
      }
      await get().refreshRuns();
      if (get().current?.activeRunId === runId) await get().selectRun(runId);
    },

    async selectRun(runId) {
      const cur = get().current;
      if (!cur) return;
      const id = cur.id;
      if (cur.activeRunId !== runId) {
        stopRunStream();
        patchCurrent(id, { activeRunId: runId, activeRun: null });
      }
      try {
        const run = await api.getRun(id, runId);
        const latest = get().current;
        if (!latest || latest.id !== id || latest.activeRunId !== runId) return;
        // While a stream is live its snapshot is the authoritative copy (it may have
        // landed before this fetch did); otherwise take the freshly fetched run, so
        // re-selecting a finished run always refreshes it.
        const streaming = runUnsubscribe !== null && latest.activeRun !== null;
        patchCurrent(id, { activeRun: streaming ? latest.activeRun : run });
        if (isRunActive(run.status) && !runUnsubscribe) subscribe(id, runId);
      } catch {
        // Leave `activeRun` null; the panel shows "could not load this run".
      }
    },

    async refreshRuns() {
      const cur = get().current;
      if (!cur) return;
      const id = cur.id;
      try {
        const runs = await api.listRuns(id);
        patchCurrent(id, { runs });
      } catch {
        // keep the runs we have
      }
    },

    // ── step picker ───────────────────────────────────────────────────────────────

    openStepPicker(index) {
      set({ stepPicker: { open: true, index } });
    },

    closeStepPicker() {
      set({ stepPicker: { open: false, index: null } });
    },

    // ── assistant ─────────────────────────────────────────────────────────────────

    async sendAssistantMessage(text) {
      const trimmed = text.trim();
      const cur = get().current;
      if (!cur || trimmed.length === 0 || get().assistant.sending) return;
      if (cur.dirty) {
        // The turn is applied to the document the *server* holds, and its echo would
        // silently replace the unsaved JSON draft on screen.
        set((s) => ({
          assistant: {
            ...s.assistant,
            error: 'Save or discard your JSON changes before asking the assistant.',
          },
        }));
        return;
      }

      const id = cur.id;
      const versionBefore = cur.versionNumber;
      // The user's bubble goes up immediately; the turn itself takes seconds. The
      // server's transcript replaces it wholesale when the response lands.
      const optimistic: AssistantMessage = { role: 'user', content: trimmed, ts: Date.now() };
      set((s) => ({
        assistant: {
          ...s.assistant,
          messages: [...s.assistant.messages, optimistic],
          sending: true,
          error: null,
        },
      }));

      const stamp = ++writeStamp;
      // Serialized with every other document write: the turn edits the document too.
      await enqueueWrite(async () => {
        try {
          const res = await api.assistant(id, trimmed);
          // Navigated away (or to another automation) while the turn was in flight.
          if (get().current?.id !== id) return;
          const before = get().current?.savedDocument ?? null;
          set((s) => ({
            assistant: {
              ...s.assistant,
              messages: res.assistantMessages,
              sending: false,
              error: null,
              lastSummary: res.summary,
              lastVersionBefore: res.operationsApplied > 0 ? versionBefore : null,
            },
          }));
          // A newer write was issued while this one was in flight — let its echo land,
          // exactly as `applyOperations` does.
          if (stamp !== writeStamp) return;
          cancelValidate();
          patchCurrent(id, {
            document: res.document,
            savedDocument: res.document,
            issues: res.issues,
            versionNumber: res.versionNumber,
            dirty: false,
            saving: false,
            saveError: null,
            saveErrorDetail: null,
            saveErrorIssues: [],
          });
          if (res.operationsApplied > 0 && before) {
            flashSteps(changedStepIds(before, res.document));
            void get().loadList();
          }
          if (res.runId) {
            // The turn asked for a test run — put the live run in front of the user.
            await get().refreshRuns();
            get().setRunPanelOpen(true);
            void get().selectRun(res.runId);
          }
        } catch (e) {
          if (get().current?.id !== id) return;
          set((s) => ({
            assistant: {
              ...s.assistant,
              sending: false,
              error: errorMessage(e, 'The assistant could not answer.'),
            },
          }));
        }
      });
    },

    /** Restores the version the last turn edited on top of. One step back, not a stack:
     *  `lastVersionBefore` is cleared afterwards, which is what disables the button. */
    async undoAssistant() {
      const cur = get().current;
      const target = get().assistant.lastVersionBefore;
      if (!cur || target === null || get().assistant.sending) return;
      const id = cur.id;
      const stamp = ++writeStamp;
      set((s) => ({ assistant: { ...s.assistant, sending: true, error: null } }));
      await enqueueWrite(async () => {
        try {
          const res = await api.restore(id, target);
          if (get().current?.id !== id) return;
          set((s) => ({
            assistant: { ...s.assistant, sending: false, lastVersionBefore: null, error: null },
          }));
          if (stamp !== writeStamp) return;
          cancelValidate();
          cancelHighlight();
          patchCurrent(id, {
            document: res.document,
            savedDocument: res.document,
            issues: res.issues,
            versionNumber: res.versionNumber,
            dirty: false,
            saving: false,
            saveError: null,
            saveErrorDetail: null,
            saveErrorIssues: [],
          });
          set({ recentlyChangedStepIds: [] });
          void get().loadList();
        } catch (e) {
          if (get().current?.id !== id) return;
          set((s) => ({
            assistant: {
              ...s.assistant,
              sending: false,
              error: errorMessage(e, 'Could not undo that change.'),
            },
          }));
        }
      });
    },

    async clearAssistant() {
      const cur = get().current;
      if (!cur) return;
      const id = cur.id;
      // Optimistic: the transcript is conversation state, nothing about the document.
      set({ assistant: EMPTY_ASSISTANT });
      try {
        await api.clearAssistant(id);
      } catch (e) {
        if (get().current?.id !== id) return;
        set((s) => ({
          assistant: {
            ...s.assistant,
            error: errorMessage(e, 'Could not clear the conversation.'),
          },
        }));
      }
    },

    setAssistantFirstMessage(text) {
      const trimmed = text.trim();
      set((s) => ({
        assistant: { ...s.assistant, pendingFirstMessage: trimmed.length > 0 ? trimmed : null },
      }));
    },

    consumeAssistantFirstMessage() {
      const pending = get().assistant.pendingFirstMessage;
      if (pending === null) return null;
      set((s) => ({ assistant: { ...s.assistant, pendingFirstMessage: null } }));
      return pending;
    },
  };
});

// ─── Selector hooks ─────────────────────────────────────────────────────────────────

/** Stable empties, so a field selector never hands zustand a fresh array (which would
 *  re-render on every store write, and warn in development). */
const NO_ISSUES: ValidationIssue[] = [];
const NO_RUNS: RunSummary[] = [];

/** The automation currently open in the editor, or null.
 *
 *  Subscribes to the *whole* slice, so every `step_text` delta of a live run re-renders
 *  the caller. Fine for a leaf that reads several fields at once (a form, a picker); the
 *  editor's big containers select single fields instead. */
export function useCurrentAutomation(): CurrentAutomation | null {
  return useAutomationsStore((s) => s.current);
}

/** Document-level validation issues, or an empty list when nothing is open. */
export function useEditorIssues(): ValidationIssue[] {
  return useAutomationsStore((s) => s.current?.issues ?? NO_ISSUES);
}

/** Per-field problems of the last rejected write — rendered inside the error banner,
 *  never by the canvas or the inspector (see `CurrentAutomation.saveErrorIssues`). */
export function useEditorSaveErrorIssues(): ValidationIssue[] {
  return useAutomationsStore((s) => s.current?.saveErrorIssues ?? NO_ISSUES);
}

/** The open automation's run history (summaries only — not the streaming detail). */
export function useEditorRuns(): RunSummary[] {
  return useAutomationsStore((s) => s.current?.runs ?? NO_RUNS);
}

/** The tool catalog, fetched on first use. Safe to call from several components at once
 *  — the request is de-duplicated and only ever runs once per session. */
export function useCatalog(): Catalog | null {
  const catalog = useAutomationsStore((s) => s.catalog);
  const loadCatalog = useAutomationsStore((s) => s.loadCatalog);
  useEffect(() => {
    void loadCatalog();
  }, [loadCatalog]);
  return catalog;
}
