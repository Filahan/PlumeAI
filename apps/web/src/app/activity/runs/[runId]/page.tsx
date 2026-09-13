'use client';

import { use } from 'react';
import RunDetail from '@/components/activity/run/run-detail';

/** `/activity/runs/{runId}` — where every square, mark and banner button in the Activity
 *  section lands. A client component because the run is read from the browser (and, while
 *  it is still going, re-read on a timer) exactly as the rest of the section is. */
export default function ActivityRunPage({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = use(params);
  return <RunDetail runId={runId} />;
}
