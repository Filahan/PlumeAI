'use client';

import { useState } from 'react';
import { CheckCheck, Copy } from 'lucide-react';

/** Shared clipboard plumbing: "copied" flips back on its own after a moment, and a
 *  blocked clipboard (insecure origin, denied permission) is silently a no-op. */
function useCopy(value: string): { copied: boolean; copy: () => Promise<void> } {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked */
    }
  };
  return { copied, copy };
}

/** A labelled single-line value from a setup guide (a redirect URI, an app id…). */
export function CopyableValue({ label, value }: { label: string; value: string }) {
  const { copied, copy } = useCopy(value);
  return (
    <div>
      <div className="text-[10px] text-[color:var(--muted-foreground)] mb-1">{label}</div>
      <div className="flex items-center gap-1.5">
        <code className="flex-1 min-w-0 truncate text-[11px] bg-[color:var(--surface-muted)] border border-[color:var(--border)] rounded-md px-2 py-1.5 font-mono">
          {value}
        </code>
        <button
          type="button"
          onClick={copy}
          aria-label={`Copy ${label}`}
          className="h-7 w-7 inline-flex items-center justify-center rounded-md bg-white border border-[color:var(--border)] text-[color:var(--muted-foreground)] hover:bg-[color:var(--surface-muted)] hover:text-[color:var(--foreground)] transition shrink-0"
        >
          {copied ? <CheckCheck size={12} strokeWidth={2} /> : <Copy size={12} strokeWidth={2} />}
        </button>
      </div>
    </div>
  );
}

/** A multi-line snippet, copied whole. */
export function CopyableCode({ value }: { value: string }) {
  const { copied, copy } = useCopy(value);
  return (
    <div className="relative">
      <pre className="text-[11px] bg-[color:var(--surface-muted)] border border-[color:var(--border)] rounded-md px-2 py-2 pr-9 font-mono overflow-x-auto whitespace-pre">
{value}
      </pre>
      <button
        type="button"
        onClick={copy}
        aria-label="Copy snippet"
        className="absolute top-1.5 right-1.5 h-6 w-6 inline-flex items-center justify-center rounded bg-white border border-[color:var(--border)] text-[color:var(--muted-foreground)] hover:bg-[color:var(--surface-muted)] hover:text-[color:var(--foreground)] transition"
      >
        {copied ? <CheckCheck size={11} strokeWidth={2} /> : <Copy size={11} strokeWidth={2} />}
      </button>
    </div>
  );
}
