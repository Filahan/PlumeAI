'use client';

import { useEffect, useRef, useState } from 'react';
import { AlertCircle, Loader2, Sparkles, Trash2, X } from 'lucide-react';
import { useAutomationsStore } from '@/lib/automations/store';
import AssistantComposer from '@/components/automations/assistant/assistant-composer';
import AssistantMessageRow from '@/components/automations/assistant/assistant-message';

/** Same confirm-in-place window the inspector and the sidebar use. */
const CONFIRM_MS = 2000;

const EXAMPLES = [
  'Every weekday at 8:00, summarise unread emails from my boss and post it to Discord',
  'Search the web for news about <topic> every morning and email me a digest',
  'Why did the last run fail?',
];

/** A request-level error mentioning a key is the one the user can actually fix, and the
 *  fix lives in Settings. Everything else (a provider outage, say) is just a sentence. */
function isMissingKey(error: string | null): boolean {
  return error !== null && /api key/i.test(error);
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
  const canUndo = useAutomationsStore((s) => s.assistant.lastVersionBefore !== null);

  const sendAssistantMessage = useAutomationsStore((s) => s.sendAssistantMessage);
  const undoAssistant = useAutomationsStore((s) => s.undoAssistant);
  const clearAssistant = useAutomationsStore((s) => s.clearAssistant);
  const setAssistantOpen = useAutomationsStore((s) => s.setAssistantOpen);
  const setRunPanelOpen = useAutomationsStore((s) => s.setRunPanelOpen);
  const selectRun = useAutomationsStore((s) => s.selectRun);

  /** Which turn's Undo has been used — it stays on screen, greyed out, so the button
   *  does not simply vanish under the cursor. */
  const [undoneIndex, setUndoneIndex] = useState<number | null>(null);
  /** Clear arms first — one click shows "Clear?", a second within two seconds does it. */
  const [armed, setArmed] = useState(false);
  const timerRef = useRef<number | undefined>(undefined);
  const listRef = useRef<HTMLDivElement>(null);

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
    setUndoneIndex(null);
    void clearAssistant();
  };

  const onViewRun = (runId: string) => {
    setRunPanelOpen(true);
    void selectRun(runId);
  };

  /** Undo belongs to the newest turn that actually applied something. */
  const lastAppliedIndex = messages.reduce(
    (found, m, i) => (m.role === 'assistant' && (m.summary?.length ?? 0) > 0 ? i : found),
    -1
  );

  return (
    <aside className="w-[380px] shrink-0 h-full border-l border-[color:var(--border)] bg-white flex flex-col">
      <div className="shrink-0 flex items-center gap-2 px-3 h-11 border-b border-[color:var(--border)]">
        <Sparkles size={13} strokeWidth={1.75} className="shrink-0" />
        <span className="min-w-0 flex-1 truncate text-[13px] font-medium">Assistant</span>
        {messages.length > 0 && (
          <button
            type="button"
            onClick={onClearClick}
            aria-label={armed ? 'Confirm clearing the conversation' : 'Clear the conversation'}
            title="Clear the conversation"
            className={`shrink-0 inline-flex items-center gap-1 h-6 px-1.5 rounded-md text-[11px] font-medium transition ${
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

      <div ref={listRef} className="flex-1 min-h-0 overflow-y-auto p-3 space-y-3">
        {messages.length === 0 ? (
          <div className="space-y-2.5">
            <p className="text-[12px] text-[color:var(--muted-foreground)]">
              Describe what you want this automation to do — the assistant edits the
              trigger and the steps for you, and can start a test run.
            </p>
            {EXAMPLES.map((example) => (
              <button
                key={example}
                type="button"
                onClick={() => void sendAssistantMessage(example)}
                disabled={sending}
                className="block w-full text-left rounded-xl border border-[color:var(--border)] px-2.5 py-2 text-[12px] leading-snug hover:bg-[color:var(--surface-muted)]/60 disabled:opacity-40 transition"
              >
                {example}
              </button>
            ))}
          </div>
        ) : (
          messages.map((message, i) => (
            <AssistantMessageRow
              key={`${message.ts}-${i}`}
              message={message}
              showUndo={i === lastAppliedIndex && (canUndo || undoneIndex === i)}
              undoDisabled={!canUndo || sending}
              onUndo={() => {
                setUndoneIndex(lastAppliedIndex);
                void undoAssistant();
              }}
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

      {error && (
        <div
          role="status"
          className="shrink-0 mx-2.5 mb-0 mt-2.5 flex items-start gap-2 rounded-xl border border-[#FDE68A] bg-[#FFFBEB] px-2.5 py-2 text-[12px] text-[#92400E]"
        >
          <AlertCircle size={13} strokeWidth={2} className="mt-[2px] shrink-0" />
          <span className="min-w-0 flex-1 break-words">{error}</span>
          {isMissingKey(error) && onOpenSettings && (
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

      <AssistantComposer sending={sending} onSend={(text) => void sendAssistantMessage(text)} />
    </aside>
  );
}
