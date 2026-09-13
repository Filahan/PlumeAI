'use client';

import { Suspense, useEffect, useRef } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { useAutomationsStore } from '@/lib/automations/store';

/** Honours `/automations/{id}?step={stepId}` by selecting that step once the automation
 *  has loaded.
 *
 *  The link comes from a failed run: "Fix this field" on the run detail page sends the
 *  reader to the exact step that broke. That is a one-shot intent rather than a piece of
 *  editor state, so the parameter is stripped as soon as it is honoured — otherwise every
 *  reload would yank the inspector back to a step the reader has long moved on from.
 *
 *  A step id that no longer exists (deleted between the run and the visit) selects
 *  nothing and the editor opens the way it normally would.
 *
 *  Rendered nowhere visible, and wrapped by `StepDeepLink` in a Suspense boundary because
 *  `useSearchParams` asks for one. */
function DeepLinkEffect({ automationId }: { automationId: string }) {
  const router = useRouter();
  const pathname = usePathname();
  const requested = useSearchParams().get('step');

  const select = useAutomationsStore((s) => s.select);
  const ready = useAutomationsStore((s) => s.current?.id === automationId);
  const hasStep = useAutomationsStore((s) =>
    requested === null
      ? false
      : (s.current?.document.steps.some((step) => step.id === requested) ?? false)
  );

  // Survives the re-render that stripping the parameter causes, so the selection happens
  // once and never fights a reader who clicks another step straight afterwards.
  const honoured = useRef<string | null>(null);

  useEffect(() => {
    if (requested === null || !ready || honoured.current === requested) return;
    honoured.current = requested;
    if (hasStep) select({ kind: 'step', stepId: requested });
    router.replace(pathname, { scroll: false });
  }, [requested, ready, hasStep, select, router, pathname]);

  return null;
}

export default function StepDeepLink({ automationId }: { automationId: string }) {
  return (
    <Suspense fallback={null}>
      <DeepLinkEffect automationId={automationId} />
    </Suspense>
  );
}
