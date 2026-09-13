'use client';

import { AlertTriangle, Check, Play, Undo2 } from 'lucide-react';
import { MarkdownRenderer } from '@/components/markdown-renderer';
import type { AssistantMessage } from '@/lib/automations/types';

/** One turn in the drawer.
 *
 *  The user's own words are a plain bubble on the right. The assistant's answer is
 *  markdown on the left, followed by whatever that turn *did*: an "Applied" block
 *  listing the changes (with Undo on the newest one), the test run it started, and — if
 *  its edits were rejected — why nothing happened. */
export default function AssistantMessageRow({
  message,
  showUndo,
  undoDisabled,
  onUndo,
  onViewRun,
}: {
  message: AssistantMessage;
  /** Only the newest turn that applied something offers Undo at all. */
  showUndo: boolean;
  /** Already used (or a write is in flight) — the button stays, greyed out. */
  undoDisabled: boolean;
  onUndo: () => void;
  onViewRun: (runId: string) => void;
}) {
  if (message.role === 'user') {
    return (
      <div className="flex justify-end">
        <p className="max-w-[86%] rounded-2xl rounded-br-md bg-[color:var(--surface-muted)] px-3 py-2 text-[13px] leading-relaxed whitespace-pre-wrap break-words">
          {message.content}
        </p>
      </div>
    );
  }

  const summary = message.summary ?? [];
  const runId = typeof message.runId === 'string' ? message.runId : null;

  return (
    <div className="space-y-2">
      {message.content && (
        <div className="[&_.prose]:text-[13px] break-words">
          <MarkdownRenderer content={message.content} />
        </div>
      )}

      {summary.length > 0 && (
        <div className="rounded-xl border border-[color:var(--border)] bg-[color:var(--surface-muted)]/50 px-2.5 py-2">
          <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[color:var(--muted-foreground)]">
            Applied
          </p>
          <ul className="mt-1 space-y-1">
            {summary.map((line, i) => (
              <li key={i} className="flex items-start gap-1.5 text-[12px] leading-snug">
                <Check size={12} strokeWidth={2.25} className="mt-[3px] shrink-0 text-[#16A34A]" />
                <span className="min-w-0 break-words">{line}</span>
              </li>
            ))}
          </ul>
          {showUndo && (
            <button
              type="button"
              onClick={onUndo}
              disabled={undoDisabled}
              className="mt-1.5 inline-flex items-center gap-1 h-6 px-1.5 -ml-1.5 rounded-md text-[11px] font-medium text-[color:var(--muted-foreground)] hover:bg-white hover:text-[color:var(--foreground)] disabled:opacity-40 transition"
            >
              <Undo2 size={12} strokeWidth={2} />
              Undo
            </button>
          )}
        </div>
      )}

      {runId && (
        <button
          type="button"
          onClick={() => onViewRun(runId)}
          className="inline-flex items-center gap-1.5 text-[11px] text-[color:var(--muted-foreground)] hover:text-[color:var(--foreground)] transition"
        >
          <Play size={11} strokeWidth={2} />
          Test run started ·{' '}
          <span className="underline underline-offset-2">View</span>
        </button>
      )}

      {typeof message.error === 'string' && message.error && (
        <p className="flex items-start gap-1.5 text-[11px] text-[#92400E]">
          <AlertTriangle size={12} strokeWidth={2} className="mt-[2px] shrink-0" />
          <span className="min-w-0 break-words">{message.error}</span>
        </p>
      )}
    </div>
  );
}
