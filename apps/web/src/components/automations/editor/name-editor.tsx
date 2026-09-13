'use client';

import { useState } from 'react';
import { useAutomationsStore } from '@/lib/automations/store';

/** Click-to-edit automation name. Commits on blur/Enter through the store's `rename`
 *  (PATCH), reverts on Escape or on failure. */
export default function NameEditor({ name }: { name: string }) {
  const rename = useAutomationsStore((s) => s.rename);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(name);

  const commit = async () => {
    setEditing(false);
    const trimmed = draft.trim();
    if (!trimmed || trimmed === name) {
      setDraft(name);
      return;
    }
    try {
      await rename(trimmed);
    } catch {
      setDraft(name);
    }
  };

  if (editing) {
    return (
      <input
        autoFocus
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => void commit()}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            (e.target as HTMLInputElement).blur();
          } else if (e.key === 'Escape') {
            setDraft(name);
            setEditing(false);
          }
        }}
        aria-label="Automation name"
        className="min-w-0 max-w-[260px] text-[15px] font-semibold tracking-tight bg-transparent outline-none border-b border-[color:var(--border)] px-0.5"
      />
    );
  }

  return (
    <button
      type="button"
      onClick={() => {
        setDraft(name);
        setEditing(true);
      }}
      title="Click to rename"
      className="min-w-0 max-w-[260px] truncate text-[15px] font-semibold tracking-tight text-left hover:bg-[color:var(--surface-muted)] rounded px-0.5 -mx-0.5 transition"
    >
      {name || 'Untitled automation'}
    </button>
  );
}
