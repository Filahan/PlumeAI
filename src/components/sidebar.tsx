'use client';

import { useCallback } from 'react';
import { Conversation, Settings } from '@/lib/types';
import { formatTokens, formatCost } from '@/lib/pricing';
import { USAGE_WINDOWS, type UsageWindow } from '@/lib/store';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter,
} from '@/components/ui/dialog';
import {
  Tooltip, TooltipTrigger, TooltipContent,
} from '@/components/ui/tooltip';
import { Button } from '@/components/ui/button';
import SettingsContent from '@/components/settings-content';
import {
  SquarePen, SearchIcon, BookMarked, Trash2, PanelLeftClose, Activity,
  Settings as SettingsIcon,
  type LucideIcon,
} from 'lucide-react';

interface SidebarProps {
  conversations: Conversation[];
  currentId: string | null;
  onSelect: (id: string) => void;
  onNewChat: () => void;
  onDelete: (id: string) => void;
  settings: Settings;
  setSettings: (s: Settings) => void;
  open: boolean;
  onToggle: () => void;
  ready: boolean;
  usage: { tokens: number; cost: number };
  conversationUsage: { tokens: number; cost: number };
  usageWindow: UsageWindow;
  onUsageWindowChange: (w: UsageWindow) => void;
  settingsOpen: boolean;
  onSettingsOpenChange: (open: boolean) => void;
}

const AppLogo = (
  <svg width="32" height="32" viewBox="0 0 36 36" fill="none">
    <rect x="2" y="2" width="32" height="32" rx="9" fill="#111111"/>
    <circle cx="18" cy="18" r="10" fill="#F5C518"/>
    <path d="M20 11l-5 7h4l-1 7 5-7h-4l1-7z" fill="#111111" stroke="#111111" strokeWidth="1" strokeLinejoin="round"/>
  </svg>
);

interface NavItemProps {
  icon: LucideIcon;
  label: string;
  open: boolean;
  onClick?: () => void;
}

function NavItem({ icon: Icon, label, open, onClick }: NavItemProps) {
  const button = (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      className={`flex items-center rounded-xl text-[16px] text-[#1c1c1c] hover:bg-[#EEEEEE] transition-colors ${
        open ? 'w-full pr-3' : 'w-10 h-10'
      }`}
    >
      <span className="w-10 h-10 flex items-center justify-center shrink-0 text-[#5a5a5a]">
        <Icon size={20} strokeWidth={2} />
      </span>
      {open && <span className="truncate text-left">{label}</span>}
    </button>
  );
  if (open) return button;
  return (
    <Tooltip>
      <TooltipTrigger render={(props) => (
        <button
          {...props}
          type="button"
          onClick={onClick}
          aria-label={label}
          className="w-10 h-10 rounded-xl flex items-center justify-center text-[#5a5a5a] hover:bg-[#EAEAEA] hover:text-[#1c1c1c] transition-colors"
        >
          <Icon size={20} strokeWidth={2} />
        </button>
      )} />
      <TooltipContent side="right" sideOffset={8}>{label}</TooltipContent>
    </Tooltip>
  );
}

export default function Sidebar({
  conversations, currentId, onSelect, onNewChat, onDelete,
  settings, setSettings, open, onToggle, ready, usage, conversationUsage, usageWindow, onUsageWindowChange,
  settingsOpen, onSettingsOpenChange,
}: SidebarProps) {
  const showConversationUsage = currentId !== null;

  const handleOpenSettings = useCallback(() => {
    onSettingsOpenChange(true);
  }, [onSettingsOpenChange]);

  const Header = (
    <div className="flex items-center justify-between shrink-0 px-4 pt-3 pb-3">
      <button
        type="button"
        onClick={onToggle}
        aria-label={open ? 'Collapse sidebar' : 'Open sidebar'}
        className="w-10 h-10 rounded-xl flex items-center justify-center hover:bg-[#EAEAEA] transition-colors shrink-0"
      >
        {AppLogo}
      </button>
      {open && (
        <button
          type="button"
          onClick={onToggle}
          aria-label="Collapse sidebar"
          className="w-10 h-10 rounded-xl flex items-center justify-center text-[#8e8e8e] hover:bg-[#EAEAEA] hover:text-[#1c1c1c] transition-colors"
        >
          <PanelLeftClose size={22} strokeWidth={2} />
        </button>
      )}
    </div>
  );

  const sectionLabelClass = 'px-4 mb-1 text-[12px] font-semibold text-[#a8a8a8] tracking-[0.08em] uppercase';

  return (
    <div
      className="flex flex-col h-full w-full overflow-hidden"
    >
      {Header}

      {/* Menu */}
      <div className="shrink-0 px-4">
        {open && <p className={sectionLabelClass}>Menu</p>}
        <div className={open ? 'space-y-0.5' : 'flex flex-col gap-1'}>
          <NavItem icon={SquarePen} label="New chat" open={open} onClick={onNewChat} />
          <NavItem icon={SearchIcon} label="Search chats" open={open} />
          <NavItem icon={BookMarked} label="Library" open={open} />
        </div>
      </div>

      {/* Recent (open only) */}
      {open ? (
        <>
          <div className="border-t border-black/[0.05] mx-3 my-3 shrink-0" />
          <div className="flex-1 overflow-hidden flex flex-col min-h-0 px-4">
            <p className={sectionLabelClass}>Recent</p>
            <div className="flex-1 overflow-y-auto space-y-0.5 pr-1 -mr-1 pb-3">
              {!ready ? null : conversations.length === 0 ? (
                <p className="px-4 py-2 text-[14px] text-[#a8a8a8]">No conversations yet</p>
              ) : (
                conversations.map((conv) => {
                  const isActive = conv.id === currentId;
                  return (
                    <div
                      key={conv.id}
                      className={`group relative rounded-xl transition-colors ${
                        isActive ? 'bg-[#EEEEEE]' : 'hover:bg-[#EEEEEE]'
                      }`}
                    >
                      <button
                        type="button"
                        onClick={() => onSelect(conv.id)}
                        className={`w-full text-left truncate text-[16px] text-[#1c1c1c] px-4 py-2 pr-9 rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#1c1c1c]/20 ${
                          isActive ? 'font-medium' : ''
                        }`}
                      >
                        {conv.title}
                      </button>
                      <button
                        type="button"
                        onClick={() => onDelete(conv.id)}
                        className="absolute right-1.5 top-1/2 -translate-y-1/2 h-7 w-7 inline-flex items-center justify-center rounded-md text-[#9b9b9b] hover:bg-[#EEEEEE] hover:text-[#D43A3A] opacity-0 group-hover:opacity-100 focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#D43A3A]/30 transition"
                        aria-label={`Delete conversation: ${conv.title}`}
                      >
                        <Trash2 size={15} strokeWidth={2} />
                      </button>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </>
      ) : (
        <div className="flex-1" />
      )}

      {/* Usage card — visible when expanded */}
      {open && ready && (
        <div className="shrink-0 px-3 pb-2">
          <div className="rounded-2xl bg-white/70 border border-black/[0.05] overflow-hidden">
            {/* Header */}
            <div className="flex items-center justify-between px-3.5 pt-3 pb-2">
              <div className="flex items-center gap-1.5">
                <span className="relative flex items-center justify-center">
                  <span className="absolute h-1.5 w-1.5 rounded-full bg-emerald-500/40 animate-ping" />
                  <span className="relative h-1.5 w-1.5 rounded-full bg-emerald-500" />
                </span>
                <span className="text-[12px] font-semibold text-[#1c1c1c] tracking-tight">Usage</span>
              </div>
              <Activity size={13} strokeWidth={2.25} className="text-emerald-600/80" />
            </div>

            {/* Current chat */}
            {showConversationUsage && (
              <>
                <div className="px-3.5 pb-3">
                  <div className="text-[10px] font-medium text-[#9b9b9b] uppercase tracking-[0.08em] mb-1.5">
                    This chat
                  </div>
                  <div className="flex items-baseline justify-between gap-3">
                    <div className="flex items-baseline gap-1">
                      <span className="text-[17px] font-semibold text-[#1c1c1c] tabular-nums leading-none">
                        {formatTokens(conversationUsage.tokens)}
                      </span>
                      <span className="text-[11px] text-[#9b9b9b]">tok</span>
                    </div>
                    <span className="text-[17px] font-semibold text-emerald-700 tabular-nums leading-none">
                      {formatCost(conversationUsage.cost)}
                    </span>
                  </div>
                </div>
                <div className="mx-3.5 border-t border-black/[0.05]" />
              </>
            )}

            {/* Time-windowed usage */}
            <div className="px-3.5 pt-2.5 pb-3">
              <div className="flex items-center justify-between mb-2">
                <span className="text-[10px] font-medium text-[#9b9b9b] uppercase tracking-[0.08em]">
                  Last
                </span>
                <div className="flex items-center gap-0.5 p-0.5 rounded-lg bg-black/[0.04]">
                  {USAGE_WINDOWS.map((w) => {
                    const active = w.id === usageWindow;
                    return (
                      <button
                        key={w.id}
                        type="button"
                        onClick={() => onUsageWindowChange(w.id)}
                        aria-pressed={active}
                        className={`px-1.5 py-0.5 rounded-md text-[10px] font-medium tabular-nums transition-colors ${
                          active
                            ? 'bg-white text-[#1c1c1c] shadow-[0_1px_2px_rgba(0,0,0,0.06)]'
                            : 'text-[#8e8e8e] hover:text-[#1c1c1c]'
                        }`}
                      >
                        {w.label}
                      </button>
                    );
                  })}
                </div>
              </div>
              <div className="flex items-baseline justify-between gap-3">
                <div className="flex items-baseline gap-1">
                  <span className="text-[17px] font-semibold text-[#1c1c1c] tabular-nums leading-none">
                    {formatTokens(usage.tokens)}
                  </span>
                  <span className="text-[11px] text-[#9b9b9b]">tok</span>
                </div>
                <span className="text-[17px] font-semibold text-emerald-700 tabular-nums leading-none">
                  {formatCost(usage.cost)}
                </span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Settings at bottom */}
      <div className="shrink-0 px-4 pb-2">
        <NavItem icon={SettingsIcon} label="Settings" open={open} onClick={handleOpenSettings} />
      </div>

      <Dialog open={settingsOpen} onOpenChange={onSettingsOpenChange}>
        <DialogContent className="sm:max-w-[520px] rounded-[24px] bg-white border-black/[0.06] shadow-2xl p-6 max-h-[85vh] overflow-y-auto">
          <DialogHeader className="space-y-1.5 pb-1">
            <DialogTitle className="text-[20px] font-semibold tracking-tight text-[#1c1c1c]">Settings</DialogTitle>
            <DialogDescription className="text-[14px] text-[#8e8e8e]">
              Configure your LLM providers and pick a default model.
            </DialogDescription>
          </DialogHeader>

          <div className="py-4">
            <SettingsContent settings={settings} setSettings={setSettings} variant="dialog" />
          </div>

          <DialogFooter className="gap-2 pt-3 border-t border-black/[0.06]">
            <Button
              onClick={() => onSettingsOpenChange(false)}
              className="h-10 px-5 rounded-xl bg-[#1c1c1c] text-white text-[14px] font-medium hover:bg-[#333]"
            >
              Done
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
