'use client';

import { Search } from 'lucide-react';
import { TOOL_FILTERS, type ToolFilter } from '@/components/tools/tool-entries';

/** Search + the four-way segment, both plain client state owned by the view. */
export default function ToolsToolbar({
  query,
  onQueryChange,
  filter,
  onFilterChange,
}: {
  query: string;
  onQueryChange: (q: string) => void;
  filter: ToolFilter;
  onFilterChange: (f: ToolFilter) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-3 flex-wrap">
      <div className="relative">
        <Search
          size={15}
          strokeWidth={2}
          aria-hidden="true"
          className="absolute left-3 top-1/2 -translate-y-1/2 text-[color:var(--muted-foreground)] pointer-events-none"
        />
        <input
          type="search"
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
          aria-label="Search tools and actions"
          placeholder="Search tools and actions"
          className="h-9 w-80 max-w-full rounded-[10px] border border-[color:var(--border)] bg-white pl-9 pr-3 text-[13px] outline-none transition placeholder:text-[color:var(--muted-foreground)] focus-visible:border-[color:var(--muted-foreground)]"
        />
      </div>

      <div
        role="group"
        aria-label="Filter tools"
        className="flex items-center gap-1 p-[3px] rounded-[10px] border border-[color:var(--border)] bg-white"
      >
        {TOOL_FILTERS.map((f) => (
          <button
            key={f.id}
            type="button"
            aria-pressed={filter === f.id}
            onClick={() => onFilterChange(f.id)}
            className={`h-7 px-3 inline-flex items-center rounded-lg text-[12px] font-medium transition ${
              filter === f.id
                ? 'bg-[color:var(--primary)] text-[color:var(--primary-foreground)]'
                : 'text-[color:var(--muted-foreground)] hover:text-[color:var(--foreground)]'
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>
    </div>
  );
}
