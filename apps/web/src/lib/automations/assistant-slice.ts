'use client';

/** The builder assistant, as a zustand slice of the automations store.
 *
 *  A turn is a document write like any other — it goes through the same queue and the
 *  same stamp rules as `applyOperations` — plus a conversation around it: what the
 *  assistant said, what it applied, the test run it started, and one step of Undo.
 *
 *  The slice needs a couple of things only the core store owns (patching `current`,
 *  cancelling the draft validation), so it is created with a small bridge rather than
 *  reaching into the store's internals.
 */

import type { StateCreator } from 'zustand';
import { automations as api } from '@/lib/api';
import { errorMessage, errorStatus } from './errors';
import { enqueueWrite, isNewestWrite, nextWriteStamp } from './write-queue';
import { documentsEqual } from './types';
import type { AssistantMessage, AutomationDocument } from './types';
import type { AutomationsStore, CurrentAutomation } from './store';

/** How long the canvas rings the steps a turn touched. */
const HIGHLIGHT_MS = 2000;

/** Said in the drawer when a turn is refused because the JSON draft is unsaved. The
 *  composer repeats it as its hint, so it lives here rather than in either component. */
export const DIRTY_REFUSAL = 'Save or discard your JSON changes before asking the assistant.';

/** The conversation and what the last turn left behind. */
export interface AssistantSlice {
  /** The transcript as the server has it, oldest first. */
  messages: AssistantMessage[];
  sending: boolean;
  /** Request-level failure — no API key for the provider, the provider itself down, a
   *  refused turn. A turn the assistant got *wrong* is not this: it rides along in the
   *  transcript as the entry's own `error`. */
  error: string | null;
  /** HTTP status behind `error`, so the drawer can tell a missing API key (404) from a
   *  provider failure (502). Null when the refusal never reached the API. */
  errorStatus: number | null;
  /** Version to restore for "Undo" — the document as it was before the last turn.
   *  Null when that turn changed nothing, when it has been undone, or when any later
   *  write has made it point at the wrong version. */
  lastVersionBefore: number | null;
  /** Queued by the home page before it navigates, addressed to the automation it just
   *  created; the editor sends it as the first message once `open(id)` has resolved. */
  pendingFirstMessage: { id: string; text: string } | null;
}

export interface AssistantState {
  assistant: AssistantSlice;
  /** Steps a turn just added or rewrote, cleared by a timeout. The canvas rings them so
   *  the user can see what the drawer is talking about. */
  recentlyChangedStepIds: string[];
}

export interface AssistantActions {
  sendAssistantMessage(text: string): Promise<void>;
  undoAssistant(): Promise<void>;
  clearAssistant(): Promise<void>;
  /** Any later document write makes Undo point at the wrong version. */
  invalidateAssistantUndo(): void;
  setAssistantFirstMessage(automationId: string, text: string): void;
  /** Returns the queued text only when it was meant for this automation. */
  consumeAssistantFirstMessage(automationId: string): string | null;
}

export type AssistantPart = AssistantState & AssistantActions;

export const EMPTY_ASSISTANT: AssistantSlice = {
  messages: [],
  sending: false,
  error: null,
  errorStatus: null,
  lastVersionBefore: null,
  pendingFirstMessage: null,
};

/** What the slice needs from the core store. */
export interface AssistantBridge {
  /** Patch `current`, but only while it is still the automation the caller was acting on. */
  patchCurrent(id: string, patch: Partial<CurrentAutomation>): void;
  /** Stop the pending draft validation — the document is about to be replaced. */
  cancelValidate(): void;
}

/** Module-scoped: the ring timer must never trigger a re-render of its own. */
let highlightTimer: ReturnType<typeof setTimeout> | null = null;

export function cancelHighlight(): void {
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

export function createAssistantSlice(
  bridge: AssistantBridge
): StateCreator<AutomationsStore, [], [], AssistantPart> {
  return (set, get) => {
    /** Merge into the conversation without touching the rest of the store. */
    const patchAssistant = (patch: Partial<AssistantSlice>): void => {
      set((s) => ({ assistant: { ...s.assistant, ...patch } }));
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

    const failed = (e: unknown, fallback: string): void => {
      patchAssistant({
        sending: false,
        error: errorMessage(e, fallback),
        errorStatus: errorStatus(e),
      });
    };

    return {
      assistant: EMPTY_ASSISTANT,
      recentlyChangedStepIds: [],

      async sendAssistantMessage(text) {
        const trimmed = text.trim();
        const cur = get().current;
        if (!cur || trimmed.length === 0 || get().assistant.sending) return;
        if (cur.dirty) {
          // The turn is applied to the document the *server* holds, and its echo would
          // silently replace the unsaved JSON draft on screen.
          patchAssistant({ error: DIRTY_REFUSAL, errorStatus: null });
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
            errorStatus: null,
          },
        }));

        const stamp = nextWriteStamp();
        // Serialized with every other document write: the turn edits the document too.
        await enqueueWrite(async () => {
          try {
            const res = await api.assistant(id, trimmed);
            // Navigated away (or to another automation) while the turn was in flight.
            if (get().current?.id !== id) return;
            const before = get().current?.savedDocument ?? null;
            // Deliberately asymmetric. The transcript is conversation state: it is the
            // user's, and it belongs on screen whatever else happened meanwhile. The
            // document may only be adopted while this is still the newest write —
            // otherwise a later edit's echo has to win, exactly as in `applyOperations`
            // — and an Undo taken past that point would restore the wrong version.
            const newest = isNewestWrite(stamp);
            patchAssistant({
              messages: res.assistantMessages,
              sending: false,
              error: null,
              errorStatus: null,
              lastVersionBefore: newest && res.operationsApplied > 0 ? versionBefore : null,
            });
            if (!newest) return;

            bridge.cancelValidate();
            bridge.patchCurrent(id, {
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
            failed(e, 'The assistant could not answer.');
          }
        });
      },

      /** Restores the version the last turn edited on top of. One step back, not a
       *  stack: `lastVersionBefore` is cleared afterwards, which is what greys the
       *  button out. */
      async undoAssistant() {
        const cur = get().current;
        const target = get().assistant.lastVersionBefore;
        if (!cur || target === null || get().assistant.sending) return;
        if (cur.dirty) {
          // Restoring would replace the document, and with it the unsaved JSON draft.
          patchAssistant({ error: DIRTY_REFUSAL, errorStatus: null });
          return;
        }
        const id = cur.id;
        const stamp = nextWriteStamp();
        patchAssistant({ sending: true, error: null, errorStatus: null });
        await enqueueWrite(async () => {
          try {
            const res = await api.restore(id, target);
            if (get().current?.id !== id) return;
            patchAssistant({ sending: false, lastVersionBefore: null, error: null });
            if (!isNewestWrite(stamp)) return;
            bridge.cancelValidate();
            cancelHighlight();
            bridge.patchCurrent(id, {
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
            failed(e, 'Could not undo that change.');
          }
        });
      },

      async clearAssistant() {
        const cur = get().current;
        // A turn in flight would land straight back on the cleared transcript.
        if (!cur || get().assistant.sending) return;
        const id = cur.id;
        // Optimistic: the transcript is conversation state, nothing about the document.
        set({ assistant: EMPTY_ASSISTANT });
        try {
          await api.clearAssistant(id);
        } catch (e) {
          if (get().current?.id !== id) return;
          failed(e, 'Could not clear the conversation.');
        }
      },

      invalidateAssistantUndo() {
        if (get().assistant.lastVersionBefore === null) return;
        patchAssistant({ lastVersionBefore: null });
      },

      setAssistantFirstMessage(automationId, text) {
        const trimmed = text.trim();
        patchAssistant({
          pendingFirstMessage: trimmed.length > 0 ? { id: automationId, text: trimmed } : null,
        });
      },

      consumeAssistantFirstMessage(automationId) {
        const pending = get().assistant.pendingFirstMessage;
        if (pending === null || pending.id !== automationId) return null;
        patchAssistant({ pendingFirstMessage: null });
        return pending.text;
      },
    };
  };
}
