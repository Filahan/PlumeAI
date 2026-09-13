'use client';

import { Switch as SwitchPrimitive } from '@base-ui/react/switch';

import { cn } from '@/lib/utils';

/** Small on/off switch, styled like the rest of the primitives: a pill that goes from
 *  `--surface-muted` to the emerald "enabled" accent used across the automations UI. */
function Switch({ className, ...props }: SwitchPrimitive.Root.Props) {
  return (
    <SwitchPrimitive.Root
      data-slot="switch"
      className={cn(
        'relative inline-flex h-[18px] w-[32px] shrink-0 cursor-pointer items-center rounded-full border border-[color:var(--border)] bg-[color:var(--surface-muted)] p-0.5 transition-colors outline-none',
        'focus-visible:ring-3 focus-visible:ring-[color:var(--ring)]/50',
        'data-checked:border-[#10A37F] data-checked:bg-[#10A37F]',
        'data-disabled:pointer-events-none data-disabled:opacity-50',
        className
      )}
      {...props}
    >
      <SwitchPrimitive.Thumb
        data-slot="switch-thumb"
        className="block size-[12px] rounded-full bg-white shadow-[0_1px_2px_rgba(0,0,0,0.12)] transition-transform data-checked:translate-x-[14px]"
      />
    </SwitchPrimitive.Root>
  );
}

export { Switch };
