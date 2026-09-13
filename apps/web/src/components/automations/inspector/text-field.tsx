'use client';

import { useEffect, useRef, useState, type RefObject } from 'react';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';

/** Shared input styling for the inspector: 12–13 px text on a white field. */
export const FIELD_CLASS =
  'h-8 rounded-lg border-[color:var(--border)] bg-white text-[13px] md:text-[13px]';

interface Common {
  value: string;
  /** Set by `LabeledField`'s render-prop form so its `<label htmlFor>` points here. */
  id?: string;
  /** Every keystroke — the caller debounces (see `useStepPatch`). */
  onChange(next: string): void;
  /** Blur or Enter, with the field's current text — the caller flushes its pending
   *  debounce, or (for fields that only commit on blur) reads the text from here. */
  onFlush?(current: string): void;
  placeholder?: string;
  'aria-label'?: string;
  className?: string;
  disabled?: boolean;
}

/** Keeps the keystrokes local while the field has focus.
 *
 *  Every commit round-trips through the server, which echoes a whole new document back;
 *  adopting that echo mid-typing would rewind the caret. So props only win when the
 *  user is looking somewhere else. */
function useDraft(value: string) {
  const [draft, setDraft] = useState(value);
  const focused = useRef(false);
  useEffect(() => {
    if (!focused.current) setDraft(value);
  }, [value]);
  return {
    draft,
    setDraft,
    onFocus: () => {
      focused.current = true;
    },
    /** Returns the draft so callers can commit it on the way out. */
    onBlur: () => {
      focused.current = false;
      return draft;
    },
  };
}

/** One-line text / number input that commits through the caller's debounce. */
export function TextField({
  id,
  value,
  onChange,
  onFlush,
  placeholder,
  className,
  disabled,
  type = 'text',
  min,
  max,
  step,
  'aria-label': ariaLabel,
}: Common & { type?: 'text' | 'number'; min?: number; max?: number; step?: number }) {
  const { draft, setDraft, onFocus, onBlur } = useDraft(value);

  return (
    <Input
      id={id}
      type={type}
      min={min}
      max={max}
      step={step}
      value={draft}
      disabled={disabled}
      placeholder={placeholder}
      aria-label={ariaLabel}
      onFocus={onFocus}
      onChange={(e) => {
        setDraft(e.target.value);
        onChange(e.target.value);
      }}
      onBlur={() => {
        const text = onBlur();
        onFlush?.(text);
      }}
      onKeyDown={(e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          (e.target as HTMLInputElement).blur();
        }
      }}
      className={cn(FIELD_CLASS, type === 'number' && 'tabular-nums', className)}
    />
  );
}

/** Multi-line text. Commits on every keystroke (debounced by the caller) and flushes on
 *  blur — Enter inserts a newline here, so it is never a commit gesture. */
export function TextAreaField({
  id,
  value,
  onChange,
  onFlush,
  placeholder,
  className,
  disabled,
  rows = 3,
  mono = false,
  inputRef,
  'aria-label': ariaLabel,
}: Common & { rows?: number; mono?: boolean; inputRef?: RefObject<HTMLTextAreaElement | null> }) {
  const { draft, setDraft, onFocus, onBlur } = useDraft(value);

  return (
    <textarea
      id={id}
      ref={inputRef}
      rows={rows}
      value={draft}
      disabled={disabled}
      placeholder={placeholder}
      aria-label={ariaLabel}
      onFocus={onFocus}
      onChange={(e) => {
        setDraft(e.target.value);
        onChange(e.target.value);
      }}
      onBlur={() => {
        const text = onBlur();
        onFlush?.(text);
      }}
      className={cn(
        'w-full rounded-lg border border-[color:var(--border)] bg-white px-2.5 py-1.5 text-[13px] leading-relaxed outline-none transition-colors resize-y',
        'placeholder:text-[color:var(--muted-foreground)] focus-visible:border-[color:var(--ring)]',
        'disabled:opacity-50 disabled:pointer-events-none',
        mono && 'font-mono text-[11px]',
        className
      )}
    />
  );
}
