'use client';

import { Plus, Sparkles } from 'lucide-react';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { useAutomationsStore } from '@/lib/automations/store';

/** What sits under the trigger while an automation has no steps.
 *
 *  It takes the place of the trailing "+ Add step" card rather than floating over the
 *  canvas, so it stays wired to the trigger by the same edge and pans with it. */
export default function EmptyState() {
  const openStepPicker = useAutomationsStore((s) => s.openStepPicker);

  return (
    <div className="h-full w-full rounded-2xl border border-dashed border-[color:var(--border)] bg-white px-4 py-4 flex flex-col items-center justify-center text-center gap-1">
      <p className="text-[14px] font-medium">Add your first step</p>
      <p className="text-[12px] text-[color:var(--muted-foreground)] leading-snug">
        Steps run top to bottom, each one using what came before it.
      </p>
      <div className="mt-2 flex items-center gap-2">
        <button
          type="button"
          onClick={() => openStepPicker(0)}
          className="inline-flex items-center gap-1.5 h-8 px-3 rounded-xl bg-[color:var(--primary)] text-white text-[12px] font-medium hover:opacity-90 transition"
        >
          <Plus size={13} strokeWidth={2.25} />
          Add a step
        </button>
        <Tooltip>
          <TooltipTrigger
            render={(props) => (
              <span {...props} className="inline-flex">
                <button
                  type="button"
                  disabled
                  className="inline-flex items-center gap-1.5 h-8 px-3 rounded-xl border border-[color:var(--border)] text-[12px] font-medium opacity-40 cursor-not-allowed"
                >
                  <Sparkles size={13} strokeWidth={2} />
                  Ask the assistant
                </button>
              </span>
            )}
          />
          <TooltipContent side="bottom">Coming soon</TooltipContent>
        </Tooltip>
      </div>
    </div>
  );
}
