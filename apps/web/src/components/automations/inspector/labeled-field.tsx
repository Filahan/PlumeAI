'use client';

import type { ReactNode } from 'react';

/** Label + optional help text above a control. The inspector's basic form row. */
export default function LabeledField({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <div className="space-y-1">
      <label className="text-[12px] font-medium">{label}</label>
      {hint && <p className="text-[11px] leading-snug text-[color:var(--muted-foreground)]">{hint}</p>}
      {children}
    </div>
  );
}
