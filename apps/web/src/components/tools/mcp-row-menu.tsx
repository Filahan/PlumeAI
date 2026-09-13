'use client';

import { Menu } from '@base-ui/react/menu';
import { Loader2, MoreHorizontal, Pencil, Power, RefreshCw, Trash2 } from 'lucide-react';

const ITEM =
  'flex items-center gap-2 h-8 px-2 rounded-lg text-[12px] cursor-default select-none outline-none data-[highlighted]:bg-[color:var(--surface-muted)] data-[disabled]:opacity-40 data-[disabled]:pointer-events-none';

/** Everything you can do to one registered server, folded into the row's right cell.
 *  Delete arms on the first click — `closeOnClick={false}` keeps the menu open so the
 *  confirmation lands on the same control instead of a new one. */
export default function McpRowMenu({
  serverName,
  enabled,
  busy,
  armed,
  open,
  onOpenChange,
  onRefresh,
  onToggle,
  onEdit,
  onDelete,
}: {
  serverName: string;
  enabled: boolean;
  busy: boolean;
  armed: boolean;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onRefresh: () => void;
  onToggle: () => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  return (
    <Menu.Root open={open} onOpenChange={onOpenChange}>
      <Menu.Trigger
        disabled={busy}
        aria-label={`Actions for ${serverName}`}
        className="h-[30px] w-[30px] inline-flex items-center justify-center rounded-[10px] border border-[color:var(--border)] bg-white text-[color:var(--muted-foreground)] transition hover:bg-[color:var(--surface-muted)] hover:text-[color:var(--foreground)] disabled:opacity-40"
      >
        {busy ? (
          <Loader2 size={13} className="animate-spin" aria-hidden="true" />
        ) : (
          <MoreHorizontal size={15} strokeWidth={2} aria-hidden="true" />
        )}
      </Menu.Trigger>

      <Menu.Portal>
        <Menu.Positioner side="bottom" align="end" sideOffset={6} className="z-50">
          <Menu.Popup className="min-w-[190px] rounded-xl border border-[color:var(--border)] bg-white p-1 shadow-lg outline-none">
            <Menu.Item className={ITEM} disabled={!enabled} onClick={onRefresh}>
              <RefreshCw size={13} strokeWidth={2} aria-hidden="true" /> Refresh tools
            </Menu.Item>
            <Menu.Item className={ITEM} onClick={onToggle}>
              <Power size={13} strokeWidth={2} aria-hidden="true" />
              {enabled ? 'Disable server' : 'Enable server'}
            </Menu.Item>
            <Menu.Item className={ITEM} onClick={onEdit}>
              <Pencil size={13} strokeWidth={2} aria-hidden="true" /> Edit server
            </Menu.Item>
            <div className="my-1 h-px bg-[color:var(--border)]" />
            <Menu.Item
              className={`${ITEM} text-[#D4183D] data-[highlighted]:bg-[#D4183D]/5`}
              closeOnClick={false}
              onClick={onDelete}
            >
              <Trash2 size={13} strokeWidth={2} aria-hidden="true" />
              {armed ? 'Click again to delete' : 'Delete server'}
            </Menu.Item>
          </Menu.Popup>
        </Menu.Positioner>
      </Menu.Portal>
    </Menu.Root>
  );
}
