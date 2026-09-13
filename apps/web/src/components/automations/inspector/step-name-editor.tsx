'use client';

import { useState } from 'react';
import { useStepPatch } from './use-step-patch';

/** Click-to-edit step name in the inspector header. Commits on blur or Enter, reverts
 *  on Escape — same gesture as the editor header's automation name. */
export default function StepNameEditor({ stepId, name }: { stepId: string; name: string }) {
  const { patchStep } = useStepPatch();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(name);

  const commit = () => {
    setEditing(false);
    const trimmed = draft.trim();
    if (!trimmed || trimmed === name) {
      setDraft(name);
      return;
    }
    patchStep(stepId, { name: trimmed });
  };

  if (editing) {
    return (
      <input
        autoFocus
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            (e.target as HTMLInputElement).blur();
          } else if (e.key === 'Escape') {
            setDraft(name);
            setEditing(false);
          }
        }}
        aria-label="Step name"
        className="min-w-0 flex-1 text-[13px] font-medium bg-transparent outline-none border-b border-[color:var(--border)] px-0.5"
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
      className="min-w-0 flex-1 truncate text-left text-[13px] font-medium hover:bg-[color:var(--surface-muted)] rounded px-0.5 -mx-0.5 transition"
    >
      {name || 'Untitled step'}
    </button>
  );
}
