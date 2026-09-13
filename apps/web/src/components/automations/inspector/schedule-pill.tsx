'use client';

import { ChevronDown } from 'lucide-react';
import { Select as SelectPrimitive } from '@base-ui/react/select';
import { Select, SelectContent, SelectItem } from '@/components/ui/select';

export interface PillOption {
  value: string;
  label: string;
}

/** One editable word of the schedule sentence: a 32px Base UI Select that reads as a
 *  chip rather than a form field.
 *
 *  The sentence is the control, so the trigger carries the `aria-label` ("Days",
 *  "Time", "Timezone") a bare `<select>` would have taken from a visible caption. */
export default function SchedulePill({
  label,
  value,
  options,
  display,
  onChange,
  numeric = false,
  wide = false,
}: {
  label: string;
  value: string;
  options: PillOption[];
  /** What the pill reads when closed — defaults to the selected option's label. */
  display?: string;
  onChange(next: string): void;
  /** Tabular figures, for times and minute counts. */
  numeric?: boolean;
  /** A long list (timezones) gets a wider popup than the pill itself. */
  wide?: boolean;
}) {
  const text = display ?? options.find((option) => option.value === value)?.label ?? value;

  return (
    <Select
      value={value}
      onValueChange={(next) => {
        if (typeof next === 'string' && next !== value) onChange(next);
      }}
    >
      <SelectPrimitive.Trigger
        aria-label={label}
        className={`inline-flex h-8 items-center gap-1.5 rounded-[10px] border border-[color:var(--border)] bg-white px-2.5 text-[14px] font-medium outline-none transition-colors select-none hover:bg-[color:var(--surface-muted)] focus-visible:border-[color:var(--ring)] focus-visible:ring-3 focus-visible:ring-[color:var(--ring)]/50 ${
          numeric ? 'tabular-nums' : ''
        }`}
      >
        <SelectPrimitive.Value>{text}</SelectPrimitive.Value>
        <ChevronDown
          size={12}
          strokeWidth={2}
          aria-hidden
          className="shrink-0 text-[color:var(--muted-foreground)]"
        />
      </SelectPrimitive.Trigger>
      <SelectContent
        align="start"
        alignItemWithTrigger={false}
        className={`max-h-[260px] p-1 ${wide ? 'w-[260px]' : 'min-w-[var(--anchor-width)] w-auto'}`}
      >
        {options.map((option) => (
          <SelectItem
            key={option.value}
            value={option.value}
            className={`text-[13px] ${numeric ? 'tabular-nums' : ''}`}
          >
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
