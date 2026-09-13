import type { ReactNode } from 'react';
import { ROW_GRID } from '@/components/tools/row-grid';

/** The bordered container every tool row lives in, with the column headings on top. The
 *  last child loses its bottom rule so the list ends flush with the container. */
export default function ToolsTable({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-2xl border border-[color:var(--border)] bg-white overflow-hidden [&>*:last-child]:border-b-0">
      <div
        className={`${ROW_GRID} py-2.5 border-b border-[color:var(--border)] bg-[#FAFAFC] text-[11px] font-semibold uppercase tracking-[0.08em] text-[color:var(--muted-foreground)]`}
      >
        <div>Tool</div>
        <div>Actions</div>
        <div>Status</div>
        <div />
      </div>
      {children}
    </div>
  );
}
