'use client';

import { useEffect, useRef, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { Plus, Trash2 } from 'lucide-react';
import { useAutomationsStore } from '@/lib/automations/store';
import { statusDot } from '@/lib/automations/format';

/** Left panel on every automations route: the list of automations, straight from the
 *  store. The active row comes from the URL, so it stays right through router
 *  navigations without any component-level selection state. */
export function AutomationsSidebar() {
  const router = useRouter();
  const pathname = usePathname();
  const activeId = pathname?.startsWith('/automations/')
    ? decodeURIComponent(pathname.slice('/automations/'.length))
    : null;

  const list = useAutomationsStore((s) => s.list);
  const listLoaded = useAutomationsStore((s) => s.listLoaded);
  const listError = useAutomationsStore((s) => s.listError);
  const loadList = useAutomationsStore((s) => s.loadList);
  const create = useAutomationsStore((s) => s.create);
  const remove = useAutomationsStore((s) => s.remove);

  const [creating, setCreating] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const resetTimerRef = useRef<number | undefined>(undefined);

  useEffect(() => {
    void loadList();
  }, [loadList]);

  useEffect(() => () => window.clearTimeout(resetTimerRef.current), []);

  /** Confirm-in-place: the trash icon arms a "Delete?" button for 2s. */
  const armDelete = (id: string) => {
    setPendingDelete(id);
    window.clearTimeout(resetTimerRef.current);
    resetTimerRef.current = window.setTimeout(() => setPendingDelete(null), 2000);
  };

  const onNew = async () => {
    if (creating) return;
    setCreating(true);
    try {
      const id = await create();
      router.push(`/automations/${id}`);
    } catch {
      // surfaced by listError
    } finally {
      setCreating(false);
    }
  };

  const onDelete = async (id: string) => {
    setPendingDelete(null);
    try {
      await remove(id);
    } catch {
      return;
    }
    if (id === activeId) router.push('/');
  };

  return (
    <aside className="w-[260px] shrink-0 h-full flex flex-col bg-[color:var(--surface-muted)] border-r border-[color:var(--border)]">
      <div className="flex items-center justify-between px-4 pt-4 pb-1">
        <span className="text-[11px] font-semibold tracking-[0.08em] uppercase text-[color:var(--muted-foreground)]">
          Automations
        </span>
        <button
          type="button"
          onClick={() => void onNew()}
          disabled={creating}
          aria-label="New automation"
          className="h-6 px-1.5 inline-flex items-center gap-1 rounded-md text-[11px] font-medium text-[color:var(--muted-foreground)] hover:bg-white hover:text-[color:var(--foreground)] disabled:opacity-40 transition"
        >
          <Plus size={13} strokeWidth={2} /> New
        </button>
      </div>

      {listError && (
        <p className="px-4 pb-1 text-[11px] text-[#D4183D]">{listError}</p>
      )}

      <div className="flex-1 overflow-y-auto px-2 pb-3">
        {!listLoaded ? null : list.length === 0 ? (
          <p className="px-3 py-2 text-[12px] text-[color:var(--muted-foreground)]">
            No automations yet
          </p>
        ) : (
          list.map((a) => {
            const isActive = a.id === activeId;
            return (
              <div
                key={a.id}
                className={`group relative rounded-lg transition-colors ${
                  isActive ? 'bg-white shadow-[0_1px_2px_rgba(0,0,0,0.04)]' : 'hover:bg-white/60'
                }`}
              >
                <button
                  type="button"
                  onClick={() => router.push(`/automations/${a.id}`)}
                  className="w-full text-left px-3 py-2 pr-9 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--ring)]"
                >
                  <div className="flex items-center gap-1.5">
                    <span
                      className={`w-1.5 h-1.5 rounded-full shrink-0 ${statusDot(a.lastRun?.status)}`}
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
                    onClick={() => void onDelete(a.id)}
                    className="absolute right-1.5 top-2 h-7 px-2 inline-flex items-center justify-center rounded-md bg-red-600 text-white text-[11px] font-medium hover:bg-red-700 transition"
                    aria-label={`Confirm delete: ${a.name}`}
                  >
                    Delete?
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => armDelete(a.id)}
                    aria-label={`Delete automation: ${a.name}`}
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

export default AutomationsSidebar;
