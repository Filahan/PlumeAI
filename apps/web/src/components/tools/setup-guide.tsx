'use client';

import { ChevronRight, ExternalLink } from 'lucide-react';
import type { ToolSetup } from '@/lib/automations/types';
import { CopyableCode, CopyableValue } from '@/components/tools/copyable';

/** "How to obtain these credentials", collapsed once they are saved.
 *
 *  `interpolate` fills the `__ORIGIN__` placeholder the backend leaves in redirect URIs —
 *  only the browser knows what this deployment is reachable at. */
export default function SetupGuide({
  setup,
  open,
  onOpenChange,
  interpolate,
}: {
  setup: ToolSetup | undefined;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  interpolate: (value: string) => string;
}) {
  return (
    <details
      open={open}
      onToggle={(e) => onOpenChange((e.target as HTMLDetailsElement).open)}
      className="rounded-xl border border-[color:var(--border)] bg-white"
    >
      <summary className="px-3 py-2.5 text-[12px] font-medium text-[color:var(--foreground)] cursor-pointer list-none flex items-center justify-between hover:bg-[color:var(--surface-muted)]/40 transition">
        <span>How to obtain these credentials</span>
        <ChevronRight
          size={14}
          strokeWidth={2}
          className={`text-[color:var(--muted-foreground)] transition-transform ${open ? 'rotate-90' : ''}`}
        />
      </summary>
      <div className="px-3 pb-3 pt-1">
        <ol className="space-y-3">
          {(setup?.steps ?? []).map((step, i) => (
            <li key={i} className="flex gap-3">
              <span className="shrink-0 w-5 h-5 rounded-full bg-[color:var(--surface-muted)] text-[color:var(--foreground)] text-[11px] font-semibold inline-flex items-center justify-center mt-0.5">
                {i + 1}
              </span>
              <div className="min-w-0 flex-1 space-y-1.5">
                <div className="text-[12px] font-medium text-[color:var(--foreground)] leading-snug">
                  {step.title}
                </div>
                {step.description && (
                  <div className="text-[11px] text-[color:var(--muted-foreground)] leading-relaxed">
                    {step.description}
                  </div>
                )}
                {step.link && (
                  <a
                    href={step.link.url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 text-[11px] underline underline-offset-2 hover:text-[color:var(--foreground)]"
                  >
                    {step.link.label} <ExternalLink size={10} strokeWidth={2} />
                  </a>
                )}
                {step.copy && (
                  <CopyableValue label={step.copy.label} value={interpolate(step.copy.value)} />
                )}
                {step.code && <CopyableCode value={interpolate(step.code)} />}
              </div>
            </li>
          ))}
        </ol>
        {setup?.note && (
          <p className="mt-3 pt-3 border-t border-[color:var(--border)] text-[11px] text-[color:var(--muted-foreground)] leading-relaxed">
            {setup.note}
          </p>
        )}
      </div>
    </details>
  );
}
