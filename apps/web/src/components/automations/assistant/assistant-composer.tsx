'use client';

import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import type { KeyboardEvent } from 'react';
import { ArrowUp, Loader2 } from 'lucide-react';

/** Tall enough for a paragraph, after which it scrolls. */
const MAX_HEIGHT = 140;

export interface AssistantComposerHandle {
  focus(): void;
  /** Put text in the box without sending it — for an example the user must fill in. */
  setText(text: string): void;
}

/** The drawer's input: one auto-growing textarea. Enter sends, Shift+Enter breaks the
 *  line — the same contract as the chat composer.
 *
 *  `onSend` answers whether the message was accepted; the box is cleared only then, so
 *  a refusal (an unsaved JSON draft, a turn still running) leaves the user's words where
 *  they typed them, with the reason underneath. */
const AssistantComposer = forwardRef<
  AssistantComposerHandle,
  {
    sending: boolean;
    /** Why sending is currently refused, if it is. */
    hint?: string | null;
    onSend: (text: string) => boolean;
  }
>(function AssistantComposer({ sending, hint = null, onSend }, ref) {
  const [text, setText] = useState('');
  const areaRef = useRef<HTMLTextAreaElement>(null);

  useImperativeHandle(ref, () => ({
    focus: () => areaRef.current?.focus(),
    setText: (next: string) => {
      setText(next);
      areaRef.current?.focus();
    },
  }));

  // The drawer has just opened (or an example was dropped in) — start typing.
  useEffect(() => {
    areaRef.current?.focus();
  }, []);

  useEffect(() => {
    const ta = areaRef.current;
    if (!ta) return;
    ta.style.height = 'auto';
    ta.style.height = `${Math.min(ta.scrollHeight, MAX_HEIGHT)}px`;
  }, [text]);

  const empty = text.trim().length === 0;

  const submit = () => {
    if (empty || sending) return;
    if (onSend(text.trim())) setText('');
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key !== 'Enter' || e.shiftKey) return;
    // Enter is inert while a turn is running; the line below says why.
    e.preventDefault();
    submit();
  };

  // Only worth saying once the user has something queued up that Enter refused to send.
  const note = hint ?? (sending && !empty ? 'Enter is paused until this turn finishes.' : null);

  return (
    <div className="shrink-0 border-t border-[color:var(--border)] p-2.5">
      <div
        className={`flex items-end gap-1.5 rounded-2xl border bg-white px-2.5 py-2 transition-colors ${
          sending
            ? 'border-[color:var(--border)] bg-[color:var(--surface-muted)]/40'
            : 'border-[color:var(--border)] focus-within:border-[color:var(--foreground)]/30'
        }`}
      >
        <textarea
          ref={areaRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
          rows={1}
          placeholder={sending ? 'Working on it…' : 'Describe what you want…'}
          aria-label="Message the assistant"
          aria-busy={sending}
          className="min-w-0 flex-1 resize-none bg-transparent text-[13px] leading-relaxed outline-none placeholder:text-[color:var(--muted-foreground)]"
        />
        <button
          type="button"
          onClick={submit}
          disabled={empty || sending}
          aria-label="Send"
          className="shrink-0 w-7 h-7 inline-flex items-center justify-center rounded-full bg-[color:var(--primary)] text-white disabled:opacity-30 hover:opacity-90 transition"
        >
          {sending ? (
            <Loader2 size={13} className="animate-spin" />
          ) : (
            <ArrowUp size={14} strokeWidth={2.25} />
          )}
        </button>
      </div>
      {note && (
        <p className="mt-1.5 px-1 text-[11px] text-[color:var(--muted-foreground)]">{note}</p>
      )}
    </div>
  );
});

export default AssistantComposer;
