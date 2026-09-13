'use client';

import { useEffect, useState } from 'react';

/** Re-render the caller every `ms` while `active`.
 *
 *  For relative timestamps ("in 12 min", "3h ago"): they are computed from `Date.now()`
 *  at render time, so without a nudge they keep claiming whatever they said when the
 *  component last rendered — which, in the editor header, can be hours. */
export function useIntervalRender(ms: number, active = true): void {
  const [, setTick] = useState(0);

  useEffect(() => {
    if (!active) return;
    const handle = window.setInterval(() => setTick((t) => t + 1), ms);
    return () => window.clearInterval(handle);
  }, [ms, active]);
}
