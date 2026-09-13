'use client';

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import type { Trigger } from '@/lib/automations/types';
import ScheduleDialogBody from './schedule-dialog-body';

/** "When should this run?" — the one schedule editor, opened from the inspector's
 *  trigger panel and from a row's Runs cell on the Schedules tab.
 *
 *  It knows nothing about where the answer goes: `onSave` is a `set_trigger` through the
 *  store in the editor and a direct API call on the Schedules tab, and the document shape
 *  it produces is identical either way. */
export default function ScheduleDialog({
  open,
  onOpenChange,
  automationName,
  trigger,
  onSave,
}: {
  open: boolean;
  onOpenChange(next: boolean): void;
  automationName: string;
  trigger: Trigger;
  onSave(next: Trigger): void | Promise<void>;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showCloseButton={false}
        className="flex max-h-[calc(100vh-4rem)] w-[560px] max-w-[calc(100%-2rem)] flex-col gap-[18px] overflow-y-auto rounded-3xl bg-white p-6 sm:max-w-[560px]"
      >
        <DialogHeader className="gap-1">
          <DialogTitle className="text-[17px] font-semibold tracking-[-0.015em]">
            When should this run?
          </DialogTitle>
          <DialogDescription className="text-[13px] leading-[18px] text-[color:var(--muted-foreground)]">
            {automationName}
          </DialogDescription>
        </DialogHeader>

        <ScheduleDialogBody
          trigger={trigger}
          onSave={onSave}
          onCancel={() => onOpenChange(false)}
        />
      </DialogContent>
    </Dialog>
  );
}
