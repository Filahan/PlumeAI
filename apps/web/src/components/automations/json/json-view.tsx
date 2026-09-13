'use client';

import { useCurrentAutomation } from '@/lib/automations/store';
import { prettyJson } from '@/lib/automations/format';
import IssuesList from '@/components/automations/issues-list';

/** JSON mode, read-only for now.
 *
 *  TEMPORARY — Task 2c replaces this with a real editor (CodeMirror or equivalent)
 *  wired to `setDocument` for local edits and the header's Save button
 *  (`saveDocument`). The plumbing is already in place: `current.document` is the draft,
 *  `current.dirty` drives Save, and `current.issues` is refreshed by the debounced
 *  `validateDraft` on every keystroke. */
export default function JsonView() {
  const current = useCurrentAutomation();
  if (!current) return null;

  return (
    <div className="h-full overflow-y-auto px-8 py-6">
      <div className="mx-auto w-full max-w-[820px] space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-[11px] uppercase tracking-[0.08em] text-[color:var(--muted-foreground)]">
            Document · v{current.versionNumber}
            {current.dirty && ' · unsaved'}
          </span>
          <span className="text-[11px] text-[color:var(--muted-foreground)]">
            Read-only until Task 2c
          </span>
        </div>

        {current.saveError && (
          <p className="text-[12px] text-[#D4183D]">{current.saveError}</p>
        )}

        <IssuesList issues={current.issues} />

        <pre className="text-[12px] font-mono whitespace-pre rounded-2xl border border-[color:var(--border)] bg-[color:var(--surface-muted)] p-4 overflow-x-auto">
          {prettyJson(current.document)}
        </pre>
      </div>
    </div>
  );
}
