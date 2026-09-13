'use client';

import type { ReactNode } from 'react';

/** One row of the step picker. Disconnected integrations render as a dimmed, inert row
 *  with a Connect shortcut instead of a choice the user cannot complete. */
export default function StepPickerItem({
  icon,
  title,
  description,
  disabled = false,
  onSelect,
  onConnect,
}: {
  icon: ReactNode;
  title: string;
  description?: string;
  disabled?: boolean;
  onSelect: () => void;
  /** When set, a "Connect" shortcut replaces the row's action. */
  onConnect?: () => void;
}) {
  return (
    <div className="relative">
      <button
        type="button"
        disabled={disabled}
        onClick={onSelect}
        className={`w-full flex items-start gap-2.5 px-2.5 py-2 rounded-xl text-left transition ${
          disabled
            ? 'opacity-45 cursor-not-allowed pr-20'
            : 'hover:bg-[color:var(--surface-muted)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--ring)]'
        }`}
      >
        <span className="mt-0.5 shrink-0">{icon}</span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13px] font-medium">{title}</span>
          {description && (
            <span className="block truncate text-[11px] text-[color:var(--muted-foreground)]">
              {description}
            </span>
          )}
        </span>
      </button>
      {disabled && onConnect && (
        <button
          type="button"
          onClick={onConnect}
          className="absolute right-2 top-1/2 -translate-y-1/2 h-6 px-2 rounded-lg border border-[color:var(--border)] bg-white text-[11px] font-medium hover:bg-[color:var(--surface-muted)] transition"
        >
          Connect
        </button>
      )}
    </div>
  );
}
