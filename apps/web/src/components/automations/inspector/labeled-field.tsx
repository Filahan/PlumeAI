'use client';

import { useId, type ReactNode } from 'react';

/** Label + optional help text above a control. The inspector's basic form row.
 *
 *  Pass a **function** as `children` when the row wraps exactly one control: it receives
 *  an id to put on that control and the caption becomes a real `<label htmlFor>`, so
 *  clicking it focuses the field and a screen reader announces the pair.
 *
 *  Rows holding a group — a mode toggle next to an input, a list of checkboxes, two
 *  selects side by side — pass plain children and get a `<span>` instead: a `<label>`
 *  pointing at nothing (or at only one of three controls) is worse than none, and those
 *  controls carry their own `aria-label`. */
export default function LabeledField({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode | ((controlId: string) => ReactNode);
}) {
  const controlId = useId();
  const single = typeof children === 'function';

  return (
    <div className="space-y-1">
      {single ? (
        <label htmlFor={controlId} className="block text-[12px] font-medium">
          {label}
        </label>
      ) : (
        <span className="block text-[12px] font-medium">{label}</span>
      )}
      {hint && (
        <p className="text-[11px] leading-snug text-[color:var(--muted-foreground)]">{hint}</p>
      )}
      {single ? children(controlId) : children}
    </div>
  );
}
