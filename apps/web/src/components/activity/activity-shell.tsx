'use client';

import type { ReactNode } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import AppShell from '@/components/app-shell';

const TABS = [
  { href: '/activity', label: 'Runs' },
  { href: '/activity/schedules', label: 'Schedules' },
  { href: '/activity/spend', label: 'Spend' },
];

interface ActivityShellProps {
  /** Page title — also what the tab bar is currently pointing at. Omitted by a detail
   *  page, which brings its own `header`. */
  title?: string;
  subtitle?: string;
  /** The header's right-hand slot: the range control on Runs, the range pills on Spend. */
  actions?: ReactNode;
  /** Replaces the title block wholesale. A run detail page opens with a breadcrumb and
   *  its own header row, but still belongs under the Runs tab — so it takes over the
   *  header rather than duplicating the shell around it. */
  header?: ReactNode;
  children: ReactNode;
}

/** The frame every Activity tab sits in: the app shell, the page header and the tab bar.
 *
 *  Each tab owns its own title and subtitle — they say different things ("Newest run on
 *  the right", "What is due, and when") — so the shell takes them as props rather than
 *  deriving them from the route. */
export default function ActivityShell({
  title,
  subtitle,
  actions,
  header,
  children,
}: ActivityShellProps) {
  const pathname = usePathname();

  return (
    <AppShell>
      <div className="h-full overflow-y-auto">
        <div className="mx-auto flex w-full max-w-[1120px] flex-col gap-[18px] px-10 py-9">
          {header ?? (
            <header className="flex items-end justify-between gap-4">
              <div className="flex flex-col gap-1.5 min-w-0">
                <h1 className="text-[20px] font-semibold leading-7 tracking-[-0.02em]">{title}</h1>
                <p className="text-[13px] leading-5 text-[color:var(--muted-foreground)]">
                  {subtitle}
                </p>
              </div>
              {actions}
            </header>
          )}

          <nav className="flex items-center gap-5 border-b border-[color:var(--border)]">
            {TABS.map((tab) => {
              // A run detail page lives under Runs — the tab it came from stays lit.
              const active =
                pathname === tab.href ||
                (tab.href === '/activity' && pathname.startsWith('/activity/runs'));
              return (
                <Link
                  key={tab.href}
                  href={tab.href}
                  aria-current={active ? 'page' : undefined}
                  className={`border-b-2 px-0.5 pb-2.5 text-[13px] font-medium transition-colors ${
                    active
                      ? 'border-[color:var(--primary)] text-[color:var(--foreground)]'
                      : 'border-transparent text-[color:var(--muted-foreground)] hover:text-[color:var(--foreground)]'
                  }`}
                >
                  {tab.label}
                </Link>
              );
            })}
          </nav>

          {children}
        </div>
      </div>
    </AppShell>
  );
}
