'use client';

import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { ArrowUp, Loader2 } from 'lucide-react';

/** Tall enough for a paragraph, after which it scrolls. */
const MAX_HEIGHT = 140;

/** The drawer's input: one auto-growing textarea. Enter sends, Shift+Enter breaks the
 *  line — the same contract as the chat composer. */
export default function AssistantComposer({
  sending,
  onSend,
}: {
  sending: boolean;
  onSend: (text: string) => void;
}) {
  const [text, setText] = useState('');
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const ta = ref.current;
    if (!ta) return;
    ta.style.height = 'auto';
    ta.style.height = `${Math.min(ta.scrollHeight, MAX_HEIGHT)}px`;
  }, [text]);

  const empty = text.trim().length === 0;

  const submit = () => {
    if (empty || sending) return;
    onSend(text.trim());
    setText('');
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key !== 'Enter' || e.shiftKey) return;
    e.preventDefault();
    submit();
  };

  return (
    <div className="shrink-0 border-t border-[color:var(--border)] p-2.5">
      <div className="flex items-end gap-1.5 rounded-2xl border border-[color:var(--border)] bg-white px-2.5 py-2 focus-within:border-[color:var(--foreground)]/30 transition-colors">
        <textarea
          ref={ref}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
          rows={1}
          placeholder="Describe what you want…"
          aria-label="Message the assistant"
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
    </div>
  );
}
