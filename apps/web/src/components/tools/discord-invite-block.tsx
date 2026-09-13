'use client';

import { useEffect, useState } from 'react';
import { AlertCircle, Check, Loader2, UserPlus } from 'lucide-react';
import { settings as settingsApi } from '@/lib/api';

interface DiscordMeta {
  bot_name: string | null;
  application_id: string | null;
  invite_url: string | null;
}

const UNREACHABLE: DiscordMeta = { bot_name: null, application_id: null, invite_url: null };

/** The step Discord's setup guide can't describe in words: once the bot token is saved,
 *  the bot still has to be *added to a server*, and only the API knows its invite URL. */
export default function DiscordInviteBlock() {
  const [meta, setMeta] = useState<DiscordMeta | null>(null);
  // Starts `true`: the fetch below is already in flight by the time anything renders.
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    settingsApi
      .discordMeta()
      .then((m) => {
        if (!cancelled) setMeta(m);
      })
      .catch(() => {
        if (!cancelled) setMeta(UNREACHABLE);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return (
      <div className="rounded-xl border border-[color:var(--border)] bg-white p-3 flex items-center gap-2 text-[12px] text-[color:var(--muted-foreground)]">
        <Loader2 size={13} className="animate-spin" />
        Checking bot…
      </div>
    );
  }

  if (!meta?.invite_url) {
    return (
      <div className="rounded-xl border border-[#D4183D]/30 bg-[#D4183D]/5 p-3 flex items-start gap-2 text-[12px] text-[#D4183D]">
        <AlertCircle size={13} strokeWidth={2.25} className="shrink-0 mt-0.5" />
        <span>Couldn&apos;t reach Discord — check your bot token above.</span>
      </div>
    );
  }

  const botName = meta.bot_name || 'Your bot';

  return (
    <div className="rounded-xl border border-[#5865F2]/30 bg-[#5865F2]/5 p-3 space-y-3">
      <div>
        <div className="text-[13px] font-medium text-[color:var(--foreground)] flex items-center gap-1.5">
          <Check size={13} strokeWidth={2.5} className="text-[#10A37F]" />
          {botName} is ready
        </div>
        <p className="text-[11px] text-[color:var(--muted-foreground)] mt-1 leading-relaxed">
          Add the bot to a Discord server so it can list channels and post messages.
        </p>
      </div>
      <a
        href={meta.invite_url}
        target="_blank"
        rel="noreferrer"
        className="inline-flex items-center justify-center gap-1.5 h-9 px-4 w-full rounded-xl bg-[#5865F2] text-white text-[13px] font-medium hover:bg-[#4752C4] transition"
        title="Required scopes: View Channels, Send Messages, Read Message History"
      >
        <UserPlus size={14} strokeWidth={2} />
        Invite to a Discord server
      </a>
    </div>
  );
}
