'use client';

import { Tabs as TabsPrimitive } from '@base-ui/react/tabs';

import { cn } from '@/lib/utils';

/** Thin wrapper over Base UI Tabs, styled like the header's Design/JSON switch: a
 *  pill-shaped segmented control on `--surface-muted` with a white active chip. */
function Tabs({ className, ...props }: TabsPrimitive.Root.Props) {
  return (
    <TabsPrimitive.Root data-slot="tabs" className={cn('flex flex-col', className)} {...props} />
  );
}

function TabsList({ className, ...props }: TabsPrimitive.List.Props) {
  return (
    <TabsPrimitive.List
      data-slot="tabs-list"
      className={cn(
        'inline-flex items-center gap-0.5 p-0.5 rounded-lg bg-[color:var(--surface-muted)]',
        className
      )}
      {...props}
    />
  );
}

function TabsTab({ className, ...props }: TabsPrimitive.Tab.Props) {
  return (
    <TabsPrimitive.Tab
      data-slot="tabs-tab"
      className={cn(
        'px-2.5 py-1 rounded-md text-[11px] font-medium text-[color:var(--muted-foreground)] outline-none select-none transition-colors',
        'hover:text-[color:var(--foreground)]',
        'focus-visible:ring-2 focus-visible:ring-[color:var(--ring)]/50',
        'data-[active]:bg-white data-[active]:text-[color:var(--foreground)] data-[active]:shadow-[0_1px_2px_rgba(0,0,0,0.06)]',
        'data-disabled:pointer-events-none data-disabled:opacity-50',
        className
      )}
      {...props}
    />
  );
}

function TabsPanel({ className, ...props }: TabsPrimitive.Panel.Props) {
  return (
    <TabsPrimitive.Panel
      data-slot="tabs-panel"
      className={cn('min-h-0 outline-none', className)}
      {...props}
    />
  );
}

export { Tabs, TabsList, TabsTab, TabsPanel };
