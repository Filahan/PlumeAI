'use client';

import { useEffect, useImperativeHandle, useMemo, useRef, useState, forwardRef } from 'react';
import { useCatalog } from '@/lib/automations/store';
import type { Catalog } from '@/lib/automations/types';

const MENTION_RE = /(^|\s)@(\w*)$/;

interface MentionItem {
  name: string;
  label: string;
  description: string;
  logoUrl?: string;
}

/** Mentionable names: one per integration (`@gmail`), plus each builtin action
 *  (`@web_search`) since builtins have no integration of their own. */
function mentionItems(catalog: Catalog | null): MentionItem[] {
  if (!catalog) return [];
  return [
    ...catalog.integrations.map((i) => ({
      name: i.name,
      label: i.label,
      description: i.description,
      logoUrl: i.logoUrl || undefined,
    })),
    ...catalog.builtinActions.map((a) => ({
      name: a.name,
      label: a.label,
      description: a.description,
    })),
  ];
}

export interface MentionAutocompleteHandle {
  /** Forward a keydown event so the popup can intercept Arrow/Enter/Tab/Escape when open. */
  handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>): boolean;
}

/**
 * Renders a floating popup of available @tools when the user types `@` followed by an optional
 * partial name in the textarea. Selection inserts `@<name> ` at the cursor.
 *
 * Hook this above a textarea, pass the same value + setter, and forward keydown via the ref:
 *   const acRef = useRef<MentionAutocompleteHandle>(null);
 *   <MentionAutocomplete ref={acRef} ... />
 *   onKeyDown={(e) => { if (acRef.current?.handleKeyDown(e)) return; ... }}
 */
const MentionAutocomplete = forwardRef<MentionAutocompleteHandle, {
  textareaRef: React.RefObject<HTMLTextAreaElement | null>;
  value: string;
  onChange: (next: string) => void;
}>(function MentionAutocomplete({ textareaRef, value, onChange }, ref) {
  const catalog = useCatalog();
  const items = useMemo(() => mentionItems(catalog), [catalog]);
  const [cursor, setCursor] = useState(0);
  const [activeIdx, setActiveIdx] = useState(0);
  const pollRef = useRef<number | null>(null);

  // Poll the textarea's selectionStart on each render — covers typing, paste, mouse clicks,
  // arrow-key navigation without wiring every event.
  useEffect(() => {
    function sync() {
      const ta = textareaRef.current;
      if (ta && ta.selectionStart !== cursor) setCursor(ta.selectionStart);
    }
    sync();
    pollRef.current = window.setInterval(sync, 80);
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
    };
  }, [textareaRef, cursor]);

  const trigger = useMemo(() => {
    const before = value.slice(0, cursor);
    const m = MENTION_RE.exec(before);
    if (!m) return null;
    const partial = m[2].toLowerCase();
    const matches = items.filter((t) => t.name.startsWith(partial));
    if (matches.length === 0) return null;
    return { partial, matches, mentionStart: before.length - m[2].length - 1 };
  }, [value, cursor, items]);

  useEffect(() => {
    if (trigger) setActiveIdx((i) => Math.min(i, trigger.matches.length - 1));
    else setActiveIdx(0);
  }, [trigger]);

  function insert(tool: MentionItem) {
    if (!trigger) return;
    const before = value.slice(0, trigger.mentionStart);
    const after = value.slice(cursor);
    const inserted = `@${tool.name} `;
    const next = before + inserted + after;
    onChange(next);
    requestAnimationFrame(() => {
      const ta = textareaRef.current;
      if (!ta) return;
      const pos = before.length + inserted.length;
      ta.setSelectionRange(pos, pos);
      ta.focus();
      setCursor(pos);
    });
  }

  useImperativeHandle(ref, () => ({
    handleKeyDown(e) {
      if (!trigger) return false;
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setActiveIdx((i) => (i + 1) % trigger.matches.length);
        return true;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        setActiveIdx((i) => (i - 1 + trigger.matches.length) % trigger.matches.length);
        return true;
      }
      if (e.key === 'Enter' || e.key === 'Tab') {
        e.preventDefault();
        insert(trigger.matches[activeIdx]);
        return true;
      }
      if (e.key === 'Escape') {
        e.preventDefault();
        setCursor((c) => c);  // force re-render with no trigger by ignoring — easiest: pretend cursor moved
        // Move cursor right before the @ so MENTION_RE no longer matches.
        const ta = textareaRef.current;
        if (ta) {
          ta.setSelectionRange(trigger.mentionStart, trigger.mentionStart);
          setCursor(trigger.mentionStart);
        }
        return true;
      }
      return false;
    },
  }), [trigger, activeIdx]);

  if (!trigger) return null;

  return (
    <div className="absolute left-3 bottom-[calc(100%+4px)] z-10 rounded-lg border border-[color:var(--border)] bg-white shadow-lg py-1 min-w-[220px] max-w-[320px]">
      {trigger.matches.map((t, i) => (
        <button
          key={t.name}
          type="button"
          onMouseDown={(e) => { e.preventDefault(); insert(t); }}
          onMouseEnter={() => setActiveIdx(i)}
          className={`w-full text-left px-3 py-1.5 text-[12px] flex items-center gap-2 transition ${
            i === activeIdx ? 'bg-[color:var(--surface-muted)]' : 'hover:bg-[color:var(--surface-muted)]/60'
          }`}
        >
          {t.logoUrl ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={t.logoUrl} alt="" className="w-4 h-4 object-contain shrink-0" />
          ) : (
            <span className="w-4 h-4 inline-block shrink-0" />
          )}
          <span className="flex flex-col min-w-0">
            <span className="font-medium">@{t.name}</span>
            <span className="text-[11px] text-[color:var(--muted-foreground)] truncate">{t.label} — {t.description}</span>
          </span>
        </button>
      ))}
    </div>
  );
});

export default MentionAutocomplete;
