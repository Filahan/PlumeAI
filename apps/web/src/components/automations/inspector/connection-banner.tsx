'use client';

import { useRouter } from 'next/navigation';
import { Plug } from 'lucide-react';
import type { CatalogIntegration } from '@/lib/automations/types';

/** Shown above an action's settings while its integration has no credentials.
 *
 *  The document stays valid — the backend only raises a *warning* for a disconnected
 *  integration — but the step cannot actually run, so say so and offer the same two
 *  routes the Tools page uses: OAuth leaves the page, config opens the tool's dialog. */
export default function ConnectionBanner({ integration }: { integration: CatalogIntegration }) {
  const router = useRouter();

  const connect = () => {
    if (integration.connectMode === 'oauth' && integration.setupUrl) {
      window.location.href = integration.setupUrl;
      return;
    }
    router.push('/tools');
  };

  return (
    <div className="rounded-xl border border-[#b45309]/30 bg-[#b45309]/5 px-3 py-2.5">
      <div className="flex items-start gap-2">
        <Plug size={13} strokeWidth={2} className="mt-0.5 shrink-0 text-[#b45309]" />
        <div className="min-w-0 flex-1">
          {/* One string, not `{label}` next to JSX text: the compiler drops the space
              between them and it renders as "Discordisn't connected". */}
          <p className="text-[12px] font-medium text-[#b45309]">
            {`${integration.label} isn’t connected`}
          </p>
          <p className="text-[11px] text-[#b45309]/80">
            Connect the account so this step can run.
          </p>
        </div>
        <button
          type="button"
          onClick={connect}
          className="shrink-0 h-7 px-2.5 rounded-lg bg-[color:var(--primary)] text-white text-[11px] font-medium hover:opacity-90 transition"
        >
          Connect
        </button>
      </div>
    </div>
  );
}
