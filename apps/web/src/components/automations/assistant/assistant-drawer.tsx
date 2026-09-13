'use client';

import { useEffect, useRef, useState } from 'react';
import { AlertCircle, Loader2, Sparkles, Trash2, X } from 'lucide-react';
import { useAutomationsStore } from '@/lib/automations/store';
import { DIRTY_REFUSAL } from '@/lib/automations/assistant-slice';
import AssistantComposer, {
  type AssistantComposerHandle,
} from '@/components/automations/assistant/assistant-composer';
import AssistantMessageRow from '@/components/automations/assistant/assistant-message';

/** Same confirm-in-place window the inspector and the sidebar use. */
const CONFIRM_MS = 2000;

/** Openers for an empty conversation. The middle one has a blank to fill in, so it goes
 *  into the composer instead of being sent as it stands. */
const EXAMPLES: { text: string; fill?: boolean }[] = [
  { text: 'Every weekday at 8:00, summarise unread emails from my boss and post it to Discord' },
  { text: 'Search the web for news about <topic> every morning and email me a digest', fill: true },
  { text: 'Why did the last run fail?' },
];

/** A 404 whose message is about a key is the one failure the user can fix, and the fix
 *  lives in Settings. A provider outage (502) reads similarly and must not point there. */
function isMissingKey(error: string | null, status: number | null): boolean {
  return error !== null && status === 404 && /api key/i.test(error);
}

/** The editor's right rail while the assistant is open: describe a change in plain
 *  language, see what it did, undo it, or jump to the test run it started.
 *
 *  It takes the inspector's slot rather than sitting next to it (`editor-shell` hides
 *  the inspector while this is open), so the canvas keeps its width. */
export default function AssistantDrawer({ onOpenSettings }: { onOpenSettings?: () => void }) {
  const messages = useAutomationsStore((s) => s.assistant.messages);
  const sending = useAutomationsStore((s) => s.assistant.sending);
  const error = useAutomationsStore((s) => s.assistant.error);
  const errorStatus = useAutomationsStore((s) => s.assistant.errorStatus);
  const undoVersion = useAutomationsStore((s) => s.assistant.lastVersionBefore);
  /** An unsaved JSON draft would be destroyed by a turn, so the store refuses one. */
  const dirty = useAutomationsStore((s) => s.current?.dirty ?? false);

  const sendAssistantMessage = useAutomationsStore((s) => s.sendAssistantMessage);
  const undoAssistant = useAutomationsStore((s) => s.undoAssistant);
  const clearAssistant = useAutomationsStore((s) => s.clearAssistant);
  const setAssistantOpen = useAutomationsStore((s) => s.setAssistantOpen);
  const setRunPanelOpen = useAutomationsStore((s) => s.setRunPanelOpen);
  const selectRun = useAutomationsStore((s) => s.selectRun);

  /** Clear arms first — one click shows "Clear?", a second within two seconds does it. */
  const [armed, setArmed] = useState(false);
  const timerRef = useRef<number | undefined>(undefined);
  const listRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<AssistantComposerHandle>(null);

  useEffect(() => () => window.clearTimeout(timerRef.current), []);

  // A new turn (or the spinner appearing) belongs at the bottom of the list.
  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages.length, sending]);

  const onClearClick = () => {
    if (!armed) {
      setArmed(true);
      window.clearTimeout(timerRef.current);
      timerRef.current = window.setTimeout(() => setArmed(false), CONFIRM_MS);
      return;
    }
    window.clearTimeout(timerRef.current);
    setArmed(false);
    void clearAssistant();
  };

  const onViewRun = (runId: string) => {
    setRunPanelOpen(true);
    void selectRun(runId);
  };

  /** The store guards this too; answering here is what lets the composer keep the text
   *  the user typed when the turn is refused. */
  const onSend = (text: string): boolean => {
    void sendAssistantMessage(text);
    return !dirty && !sending;
  };

  /** Undo belongs to the newest turn that actually applied something. It stays on that
   *  turn once it is no longer usable — undone, or overtaken by a later edit — rather
   *  than disappearing from under the cursor. */
  const lastAppliedIndex = messages.reduce((found, m, i) => {
    const applied = m.role === 'assistant' && Array.isArray(m.summary) && m.summary.length > 0;
    return applied ? i : found;
  }, -1);

  return (
    <aside
      aria-label="Assistant"
      className="w-[380px] shrink-0 h-full border-l border-[color:var(--border)] bg-white flex flex-col"
    >
      <div className="shrink-0 flex items-center gap-2 px-3 h-11 border-b border-[color:var(--border)]">
        <Sparkles size={13} strokeWidth={1.75} className="shrink-0" />
        <span className="min-w-0 flex-1 truncate text-[13px] font-medium">Assistant</span>
        {messages.length > 0 && (
          <button
            type="button"
            onClick={onClearClick}
            disabled={sending}
            aria-label={armed ? 'Confirm clearing the conversation' : 'Clear the conversation'}
            title={sending ? 'Wait for the current turn to finish' : 'Clear the conversation'}
            className={`shrink-0 inline-flex items-center gap-1 h-6 px-1.5 rounded-md text-[11px] font-medium disabled:opacity-40 transition ${
              armed
                ? 'bg-[#D4183D] text-white'
                : 'text-[color:var(--muted-foreground)] hover:bg-[color:var(--surface-muted)] hover:text-[color:var(--foreground)]'
            }`}
          >
            <Trash2 size={13} strokeWidth={2} />
            {armed ? 'Clear?' : 'Clear'}
          </button>
        )}
        <button
          type="button"
          onClick={() => setAssistantOpen(false)}
          aria-label="Close the assistant"
          className="shrink-0 w-6 h-6 inline-flex items-center justify-center rounded-md text-[color:var(--muted-foreground)] hover:bg-[color:var(--surface-muted)] hover:text-[color:var(--foreground)] transition"
        >
          <X size={13} strokeWidth={2} />
        </button>
      </div>

      <div
        ref={listRef}
        role="log"
        aria-live="polite"
        className="flex-1 min-h-0 overflow-y-auto p-3 space-y-3"
      >
        {messages.length === 0 ? (
          <div className="space-y-2.5">
            <p className="text-[12px] text-[color:var(--muted-foreground)]">
              Describe what you want this automation to do — the assistant edits the
              trigger and the steps for you, and can start a test run.
            </p>
            {EXAMPLES.map((example) => (
              <button
                key={example.text}
                type="button"
                onClick={() =>
                  example.fill
                    ? composerRef.current?.setText(example.text)
                    : void sendAssistantMessage(example.text)
                }
                disabled={sending}
                title={example.fill ? 'Fill in the blank, then send' : undefined}
                className="block w-full text-left rounded-xl border border-[color:var(--border)] px-2.5 py-2 text-[12px] leading-snug hover:bg-[color:var(--surface-muted)]/60 disabled:opacity-40 transition"
              >
                {example.text}
              </button>
            ))}
          </div>
        ) : (
          messages.map((message, i) => (
            <AssistantMessageRow
              key={`${message.ts}-${i}`}
              message={message}
              showUndo={i === lastAppliedIndex}
              undoVersion={undoVersion}
              undoDisabled={undoVersion === null || sending}
              onUndo={() => void undoAssistant()}
              onViewRun={onViewRun}
            />
          ))
        )}

        {sending && (
          <p className="flex items-center gap-1.5 text-[12px] text-[color:var(--muted-foreground)]">
            <Loader2 size={12} className="animate-spin" /> Working on it…
          </p>
        )}
      </div>

      {/* The refusal to overwrite a JSON draft is the composer's hint, not a banner. */}
      {error && error !== DIRTY_REFUSAL && (
        <div
          role="alert"
          className="shrink-0 mx-2.5 mt-2.5 flex items-start gap-2 rounded-xl border border-[#FDE68A] bg-[#FFFBEB] px-2.5 py-2 text-[12px] text-[#92400E]"
        >
          <AlertCircle size={13} strokeWidth={2} className="mt-[2px] shrink-0" />
          <span className="min-w-0 flex-1 break-words">{error}</span>
          {isMissingKey(error, errorStatus) && onOpenSettings && (
            <button
              type="button"
              onClick={onOpenSettings}
              className="shrink-0 font-medium underline underline-offset-2 hover:opacity-80"
            >
              Settings
            </button>
          )}
        </div>
      )}

      <AssistantComposer
        ref={composerRef}
        sending={sending}
        hint={dirty ? DIRTY_REFUSAL : null}
        onSend={onSend}
      />
    </aside>
  );
}
