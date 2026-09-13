'use client';

import { useState, type ReactNode } from 'react';
import { Check, ChevronRight } from 'lucide-react';
import { useCatalog } from '@/lib/automations/store';
import { BUILTIN_INTEGRATION, type CatalogAction } from '@/lib/automations/types';

interface Group {
  name: string;
  label: string;
  connected: boolean;
  actions: CatalogAction[];
}

/** Which tools an AI step may call, grouped by integration. Tools from a disconnected
 *  account are greyed but still selectable — connecting later shouldn't mean rebuilding
 *  the step. */
export default function AiToolsPicker({
  selected,
  onChange,
}: {
  selected: string[];
  onChange(next: string[]): void;
}) {
  const catalog = useCatalog();

  const groups: Group[] = catalog
    ? [
        ...catalog.integrations.map((i) => ({
          name: i.name,
          label: i.label,
          connected: i.connected,
          actions: i.actions,
        })),
        {
          name: BUILTIN_INTEGRATION,
          label: 'Built-in',
          connected: true,
          actions: catalog.builtinActions,
        },
      ].filter((g) => g.actions.length > 0)
    : [];

  const toggle = (name: string) =>
    onChange(
      selected.includes(name) ? selected.filter((t) => t !== name) : [...selected, name]
    );

  if (catalog === null) {
    return (
      <p className="text-[11px] text-[color:var(--muted-foreground)]">Loading the tool list…</p>
    );
  }

  return (
    <div className="space-y-1">
      {groups.map((group) => {
        const count = group.actions.filter((a) => selected.includes(a.name)).length;
        return (
          <GroupDetails
            key={group.name}
            defaultOpen={count > 0}
            summary={
              <>
                <ChevronRight
                  size={11}
                  strokeWidth={2}
                  className="shrink-0 text-[color:var(--muted-foreground)] transition-transform group-open:rotate-90"
                />
                <span className="font-medium truncate">{group.label}</span>
                {!group.connected && (
                  <span className="text-[10px] text-[#b45309] shrink-0">not connected</span>
                )}
                <span className="ml-auto shrink-0 text-[10px] tabular-nums text-[color:var(--muted-foreground)]">
                  {count > 0 ? `${count} on` : `${group.actions.length}`}
                </span>
              </>
            }
          >
            <div className="mt-1 space-y-0.5">
              {group.actions.map((action) => {
                const on = selected.includes(action.name);
                return (
                  <button
                    key={action.name}
                    type="button"
                    role="checkbox"
                    aria-checked={on}
                    onClick={() => toggle(action.name)}
                    className={`w-full flex items-start gap-1.5 px-1 py-1 rounded-lg text-left hover:bg-[color:var(--surface-muted)]/70 transition ${
                      group.connected ? '' : 'opacity-55'
                    }`}
                  >
                    <span
                      aria-hidden
                      className={`mt-[1px] w-3.5 h-3.5 shrink-0 rounded-[4px] border inline-flex items-center justify-center ${
                        on
                          ? 'bg-[#10A37F] border-[#10A37F] text-white'
                          : 'border-[color:var(--border)] bg-white'
                      }`}
                    >
                      {on && <Check size={9} strokeWidth={3} />}
                    </span>
                    <span className="min-w-0">
                      <span className="block text-[12px] truncate">{action.label}</span>
                      <span className="block text-[10px] font-mono text-[color:var(--muted-foreground)] truncate">
                        {action.name}
                      </span>
                    </span>
                  </button>
                );
              })}
            </div>
          </GroupDetails>
        );
      })}
    </div>
  );
}

/** `open` on a `<details>` is a *controlled* attribute: driving it from the selection
 *  count meant the group sprang back open the moment the user collapsed it (and the last
 *  tool they unticked slammed it shut). The count only decides the initial state now. */
function GroupDetails({
  defaultOpen,
  summary,
  children,
}: {
  defaultOpen: boolean;
  summary: ReactNode;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <details
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
      className="group rounded-xl border border-[color:var(--border)] px-2.5 py-1.5"
    >
      <summary className="flex items-center gap-1.5 cursor-pointer list-none text-[12px]">
        {summary}
      </summary>
      {children}
    </details>
  );
}
