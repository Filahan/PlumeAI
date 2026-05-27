'use client';

import { useCallback, useRef, useState } from 'react';
import { Conversation, Settings } from '@/lib/types';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter,
} from '@/components/ui/dialog';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip';
import { Button } from '@/components/ui/button';
import SettingsContent from '@/components/settings-content';
import {
  SquarePen, Activity, Settings as SettingsIcon, Plus, Trash2,
  type LucideIcon,
} from 'lucide-react';
import { useRouter } from 'next/navigation';

interface NavRailProps {
  settings: Settings;
  setSettings: (s: Settings) => void;
  settingsOpen: boolean;
  onSettingsOpenChange: (open: boolean) => void;
  onNewChat: () => void;
  onToggleSidebar: () => void;
}

function RailIcon({ icon: Icon, label, onClick, active }: {
  icon: LucideIcon; label: string; onClick?: () => void; active?: boolean;
}) {
  return (
    <Tooltip>
      <TooltipTrigger render={(props) => (
        <button
          {...props}
          type="button"
          onClick={onClick}
          aria-label={label}
          className={`w-10 h-10 rounded-xl flex items-center justify-center transition-colors ${
            active ? 'bg-[color:var(--surface-muted)] text-[color:var(--foreground)]' : 'text-[color:var(--muted-foreground)] hover:bg-[color:var(--surface-muted)] hover:text-[color:var(--foreground)]'
          }`}
        >
          <Icon size={18} strokeWidth={1.75} />
        </button>
      )} />
      <TooltipContent side="right" sideOffset={8}>{label}</TooltipContent>
    </Tooltip>
  );
}

export function NavRail({ settings, setSettings, settingsOpen, onSettingsOpenChange, onNewChat, onToggleSidebar }: NavRailProps) {
  const router = useRouter();
  const handleOpenSettings = useCallback(() => onSettingsOpenChange(true), [onSettingsOpenChange]);

  return (
    <>
      <aside className="w-[72px] shrink-0 h-full flex flex-col items-center bg-white border-r border-[color:var(--border)] py-3">
        <button
          type="button"
          onClick={onToggleSidebar}
          aria-label="Toggle conversation list"
          className="w-10 h-10 rounded-xl flex items-center justify-center hover:bg-[color:var(--surface-muted)] transition-colors mb-2"
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/logo.png" alt="" className="h-6 w-auto" />
        </button>

        <div className="w-8 border-t border-[color:var(--border)] my-2" />

        <div className="flex flex-col gap-1">
          <RailIcon icon={SquarePen} label="New chat" onClick={onNewChat} />
          <RailIcon icon={Activity} label="Usage" onClick={() => router.push('/usage')} />
        </div>

        <div className="flex-1" />

        <RailIcon icon={SettingsIcon} label="Settings" onClick={handleOpenSettings} />
      </aside>

      <Dialog open={settingsOpen} onOpenChange={onSettingsOpenChange}>
        <DialogContent className="sm:max-w-[520px] rounded-[24px] bg-white border-[color:var(--border)] shadow-2xl p-6 max-h-[85vh] overflow-y-auto">
          <DialogHeader className="space-y-1.5 pb-1">
            <DialogTitle className="text-[17px] font-semibold tracking-tight">Settings</DialogTitle>
            <DialogDescription className="text-[13px] text-[color:var(--muted-foreground)]">
              Configure your LLM providers and pick a default model.
            </DialogDescription>
          </DialogHeader>
          <div className="py-4">
            <SettingsContent settings={settings} setSettings={setSettings} variant="dialog" />
          </div>
          <DialogFooter className="gap-2 pt-3 border-t border-[color:var(--border)]">
            <Button
              onClick={() => onSettingsOpenChange(false)}
              className="h-9 px-4 rounded-xl bg-[color:var(--primary)] text-white text-[13px] font-medium hover:opacity-90"
            >
              Done
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

interface ConversationListPanelProps {
  conversations: Conversation[];
  currentId: string | null;
  onSelect: (id: string) => void;
  onNewChat: () => void;
  onDelete: (id: string) => void;
  ready: boolean;
}

export function ConversationListPanel({
  conversations, currentId, onSelect, onNewChat, onDelete, ready,
}: ConversationListPanelProps) {
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const resetTimerRef = useRef<number | undefined>(undefined);
  const armDelete = (id: string) => {
    setPendingDelete(id);
    if (resetTimerRef.current) window.clearTimeout(resetTimerRef.current);
    resetTimerRef.current = window.setTimeout(() => setPendingDelete(null), 2000);
  };
  return (
    <aside className="w-[260px] shrink-0 h-full flex flex-col bg-[color:var(--surface-muted)] border-r border-[color:var(--border)]">
      <div className="px-4 pt-4 pb-2 shrink-0">
        <button
          type="button"
          onClick={onNewChat}
          className="w-full inline-flex items-center justify-center gap-2 h-10 rounded-full bg-[color:var(--primary)] text-white text-[13px] font-medium hover:opacity-90 transition"
        >
          <Plus size={15} strokeWidth={2.25} />
          New chat
        </button>
      </div>

      <div className="px-4 pt-3 pb-1 text-[11px] font-semibold tracking-[0.08em] uppercase text-[color:var(--muted-foreground)]">
        Recent
      </div>
      <div className="flex-1 overflow-y-auto px-2 pb-3">
        {!ready ? null : conversations.length === 0 ? (
          <p className="px-3 py-2 text-[12px] text-[color:var(--muted-foreground)]">No conversations yet</p>
        ) : (
          conversations.map((conv) => {
            const isActive = conv.id === currentId;
            return (
              <div
                key={conv.id}
                className={`group relative rounded-lg transition-colors ${
                  isActive ? 'bg-white shadow-[0_1px_2px_rgba(0,0,0,0.04)]' : 'hover:bg-white/60'
                }`}
              >
                <button
                  type="button"
                  onClick={() => onSelect(conv.id)}
                  className={`w-full text-left truncate text-[13px] px-3 py-2 pr-9 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--ring)] ${
                    isActive ? 'font-medium' : ''
                  }`}
                >
                  {conv.title}
                </button>
                {pendingDelete === conv.id ? (
                  <button
                    type="button"
                    onClick={() => { onDelete(conv.id); setPendingDelete(null); }}
                    className="absolute right-1.5 top-1/2 -translate-y-1/2 h-7 px-2 inline-flex items-center justify-center rounded-md bg-red-600 text-white text-[11px] font-medium hover:bg-red-700 transition"
                    aria-label={`Confirm delete: ${conv.title}`}
                  >
                    Delete?
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => armDelete(conv.id)}
                    className="absolute right-1.5 top-1/2 -translate-y-1/2 h-7 w-7 inline-flex items-center justify-center rounded-md text-[color:var(--muted-foreground)] hover:bg-[color:var(--surface-muted)] hover:text-red-600 opacity-0 group-hover:opacity-100 focus-visible:opacity-100 transition"
                    aria-label={`Delete conversation: ${conv.title}`}
                  >
                    <Trash2 size={13} strokeWidth={1.75} />
                  </button>
                )}
              </div>
            );
          })
        )}
      </div>
    </aside>
  );
}
