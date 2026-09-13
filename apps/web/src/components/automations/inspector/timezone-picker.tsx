'use client';

import { ChevronsUpDown } from 'lucide-react';
import { Combobox } from '@base-ui/react/combobox';

/** IANA's list is ~430 entries, which is unusable as a scroll-only Select. Only this
 *  many matches are ever rendered — typing narrows it long before that matters. */
const VISIBLE_LIMIT = 60;

/** Timezone chooser: type to filter, pick from what's left.
 *
 *  Base UI's Combobox does the filtering, the listbox semantics and the keyboard
 *  handling; all this file owns is the token styling and the "only commit real zones"
 *  rule — a half-typed `Europe/Par` must not reach `set_trigger`. */
export default function TimezonePicker({
  value,
  zones,
  onChange,
  id,
}: {
  value: string;
  zones: string[];
  onChange(next: string): void;
  id?: string;
}) {
  return (
    <Combobox.Root
      items={zones}
      value={value}
      limit={VISIBLE_LIMIT}
      openOnInputClick
      onValueChange={(next) => {
        // `null` is "the input was cleared" — keep the trigger's current zone rather
        // than sending an empty one the document schema would reject.
        if (typeof next === 'string' && next.length > 0 && next !== value) onChange(next);
      }}
    >
      <div className="relative">
        <Combobox.Input
          id={id}
          aria-label="Timezone"
          placeholder="Search timezones…"
          className="w-full h-8 pl-2.5 pr-7 rounded-lg border border-[color:var(--border)] bg-white text-[13px] outline-none transition-colors placeholder:text-[color:var(--muted-foreground)] focus-visible:border-[color:var(--ring)]"
        />
        <Combobox.Trigger
          aria-label="Show timezones"
          className="absolute right-1 top-1/2 -translate-y-1/2 inline-flex h-6 w-6 items-center justify-center rounded-md text-[color:var(--muted-foreground)] hover:text-[color:var(--foreground)]"
        >
          <ChevronsUpDown size={12} strokeWidth={2} />
        </Combobox.Trigger>
      </div>

      <Combobox.Portal>
        <Combobox.Positioner sideOffset={4} className="z-50">
          <Combobox.Popup className="max-h-[240px] w-[var(--anchor-width)] overflow-y-auto rounded-xl border border-[color:var(--border)] bg-white p-1 shadow-[0_8px_24px_rgba(0,0,0,0.10)]">
            <Combobox.Empty className="px-2 py-1.5 text-[12px] text-[color:var(--muted-foreground)]">
              No timezone matches that.
            </Combobox.Empty>
            <Combobox.List>
              {(zone: string) => (
                <Combobox.Item
                  key={zone}
                  value={zone}
                  className="cursor-default select-none rounded-lg px-2 py-1.5 text-[13px] data-[highlighted]:bg-[color:var(--surface-muted)] data-[selected]:font-medium"
                >
                  {zone}
                </Combobox.Item>
              )}
            </Combobox.List>
          </Combobox.Popup>
        </Combobox.Positioner>
      </Combobox.Portal>
    </Combobox.Root>
  );
}
