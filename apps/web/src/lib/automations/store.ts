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

export type EditorMode = 'design' | 'json';

/** What the inspector is pointed at. `null` = nothing selected. */
export type Selection = { kind: 'trigger' } | { kind: 'step'; stepId: string } | null;

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

function enqueueWrite<T>(task: () => Promise<T>): Promise<T> {
  // `then(task, task)` so one rejected write does not poison the queue behind it.
  const run = writeQueue.then(task, task);
  writeQueue = run.then(
    () => undefined,
    () => undefined
  );
  return run;
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

/** Per-field problems the API attached to a rejected write. `ApiError` already
 *  normalized the three possible envelopes (see `lib/api/client.ts`). */
function issuesFromError(e: unknown): ValidationIssue[] | null {
  if (!(e instanceof ApiError)) return null;
  return e.issues.length > 0 ? e.issues : null;
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
      if (evt.type === 'run_finished') {
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
            selection: null,
            mode: 'design',
            pendingModeSwitch: null,
            inspectorOpen: true,
            runPanelOpen: false,
            assistantOpen: false,
            runs,
            activeRunId: latest?.id ?? null,
            activeRun: null,
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
      openToken += 1;
      set({ current: null, currentLoading: false, currentError: null });
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
      patchCurrent(id, { saving: true, saveError: null, saveErrorDetail: null });
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
          });
          void get().loadList();
        } catch (e) {
          if (stamp === writeStamp) {
            const issues = issuesFromError(e);
            patchCurrent(id, {
              saving: false,
              saveError: "That change wasn't accepted.",
              saveErrorDetail: errorDetail(e),
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
      patchCurrent(id, { saving: true, saveError: null, saveErrorDetail: null });
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
          });
          void get().loadList();
        } catch (e) {
          if (stamp !== writeStamp) return;
          // 422 → keep the draft (and its dirty flag) so the user can fix it in place.
          const issues = issuesFromError(e);
          patchCurrent(id, {
            saving: false,
            saveError: "That change wasn't accepted.",
            saveErrorDetail: errorDetail(e),
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
            ? { saveError: 'A run is already in progress.', saveErrorDetail: null }
            : {
                saveError: errorMessage(e, 'Failed to start run'),
                saveErrorDetail: errorDetail(e),
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
