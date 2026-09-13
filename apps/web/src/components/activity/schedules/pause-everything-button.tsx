'use client';

import { useEffect, useRef, useState } from 'react';
import { Pause, Play } from 'lucide-react';

/** Same confirm-in-place window the inspector, the sidebar and the assistant use. */
const CONFIRM_MS = 2000;

/** Stop (or restart) every schedule at once.
 *
 *  Arms first: one click asks, a second within two seconds does it, and the question
 *  lands on the button you already clicked rather than in a modal. Pausing keeps every
 *  schedule exactly where it is — the button is reversible, which is why it does not
 *  deserve a dialog. */
export default function PauseEverythingButton({
  allPaused,
  busy,
  onConfirm,
}: {
  /** Every schedule is already off, so the button offers the other direction. */
  allPaused: boolean;
  busy: boolean;
  onConfirm(enabled: boolean): void;
}) {
  /** Stored as the direction it was armed *for*, not as a flag: somebody flipping the
   *  last switch by hand changes what this button would do, and an armed "Pause
   *  everything?" must not answer a question nobody asked. */
  const [armedFor, setArmedFor] = useState<boolean | null>(null);
  const timerRef = useRef<number | undefined>(undefined);

  useEffect(() => () => window.clearTimeout(timerRef.current), []);

  const armed = armedFor !== null && armedFor === allPaused;
  const label = allPaused ? 'Resume everything' : 'Pause everything';
  const Icon = allPaused ? Play : Pause;

  const onClick = () => {
    if (!armed) {
      setArmedFor(allPaused);
      window.clearTimeout(timerRef.current);
      timerRef.current = window.setTimeout(() => setArmedFor(null), CONFIRM_MS);
      return;
    }
    window.clearTimeout(timerRef.current);
    setArmedFor(null);
    onConfirm(allPaused);
  };

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={busy}
      className="flex h-8 items-center gap-1.5 whitespace-nowrap rounded-[10px] border border-[color:var(--border)] bg-white px-3 text-[13px] font-medium outline-none transition-colors hover:bg-[color:var(--surface-muted)] focus-visible:ring-3 focus-visible:ring-[color:var(--ring)]/50 disabled:pointer-events-none disabled:opacity-50"
    >
      <Icon size={14} strokeWidth={2} aria-hidden className="shrink-0" />
      {armed ? `${label}?` : label}
    </button>
  );
}
