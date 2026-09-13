import type { ReactNode } from 'react';

/** The calm version of "there is nothing here".
 *
 *  Used for three different nothings: no automations yet, no runs in the selected range,
 *  and a run feed that did not answer — the last one is a state to explain, not an error
 *  to throw at someone. */
export default function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon?: ReactNode;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center rounded-2xl border border-[color:var(--border)] bg-white px-6 py-14 text-center">
      {icon && (
        <div className="mb-4 flex h-11 w-11 items-center justify-center rounded-xl border border-[color:var(--border)] bg-[color:var(--surface-muted)] text-[color:var(--muted-foreground)]">
          {icon}
        </div>
      )}
      <h2 className="text-[15px] font-semibold">{title}</h2>
      <p className="mt-1 max-w-[420px] text-[13px] leading-5 text-[color:var(--muted-foreground)]">
        {description}
      </p>
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}
