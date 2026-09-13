'use client';

import { useState } from 'react';
import { AutomationSummary } from '@/lib/types';
import { RUN_STATUS_DOT } from '@/components/automations/view';
import { Plus, Trash2 } from 'lucide-react';

export function AutomationsSidebar({
  automations, loaded, selectedId, onSelect, onNew, onDelete,
}: {
  automations: AutomationSummary[];
  loaded: boolean;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
}) {
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);

  return (
    <aside className="w-[260px] shrink-0 h-full flex flex-col bg-[color:var(--surface-muted)] border-r border-[color:var(--border)]">
      <div className="flex items-center justify-between px-4 pt-4 pb-1">
        <span className="text-[11px] font-semibold tracking-[0.08em] uppercase text-[color:var(--muted-foreground)]">
          Automations
        </span>
        <button
          type="button"
          onClick={onNew}
          aria-label="New automation"
          className="h-6 w-6 inline-flex items-center justify-center rounded-md text-[color:var(--muted-foreground)] hover:bg-white hover:text-[color:var(--foreground)] transition"
        >
          <Plus size={15} strokeWidth={2} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-2 pb-3">
        {!loaded ? null : automations.length === 0 ? (
          <p className="px-3 py-2 text-[12px] text-[color:var(--muted-foreground)]">
            No automations yet
          </p>
        ) : (
          automations.map((a) => {
            const isActive = a.id === selectedId;
            const runDot = a.lastRun ? RUN_STATUS_DOT[a.lastRun.status] ?? 'bg-gray-300' : 'bg-gray-300';
            return (
              <div
                key={a.id}
                className={`group relative rounded-lg transition-colors ${
                  isActive ? 'bg-white shadow-[0_1px_2px_rgba(0,0,0,0.04)]' : 'hover:bg-white/60'
                }`}
              >
                <button
                  type="button"
                  onClick={() => onSelect(a.id)}
                  className="w-full text-left px-3 py-2 pr-9 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--ring)]"
                >
                  <div className="flex items-center gap-1.5">
                    <span
                      className={`w-1.5 h-1.5 rounded-full shrink-0 ${runDot}`}
                      title={a.lastRun ? `Last run: ${a.lastRun.status}` : 'No runs yet'}
                    />
                    <span className={`truncate text-[13px] ${isActive ? 'font-medium' : ''}`}>
                      {a.name || 'Untitled automation'}
                    </span>
                    <span
                      className={`ml-auto w-1.5 h-1.5 rounded-full shrink-0 ${
                        a.enabled ? 'bg-[#10A37F]' : 'bg-[color:var(--muted-foreground)]/30'
                      }`}
                      title={a.enabled ? 'Enabled' : 'Disabled'}
                    />
                  </div>
                  <div className="mt-1 truncate text-[11px] text-[color:var(--muted-foreground)]">
                    {a.triggerSummary}
                    {!a.valid && <span className="text-[#D4183D]"> · has issues</span>}
                  </div>
                </button>
                {pendingDelete === a.id ? (
                  <button
                    type="button"
                    onClick={() => { onDelete(a.id); setPendingDelete(null); }}
                    className="absolute right-1.5 top-2 h-7 px-2 inline-flex items-center justify-center rounded-md bg-red-600 text-white text-[11px] font-medium hover:bg-red-700 transition"
                  >
                    Delete?
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => setPendingDelete(a.id)}
                    aria-label="Delete automation"
                    className="absolute right-1.5 top-2 h-7 w-7 inline-flex items-center justify-center rounded-md text-[color:var(--muted-foreground)] hover:bg-[color:var(--surface-muted)] hover:text-red-600 opacity-0 group-hover:opacity-100 focus-visible:opacity-100 transition"
                  >
                    <Trash2 size={13} strokeWidth={1.75} />
                  </button>
                )}
              </div>
            );
          })
        )}
      </div>
    </aside>
  );
}
