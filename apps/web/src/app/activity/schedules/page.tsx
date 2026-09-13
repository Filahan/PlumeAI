import ActivityShell from '@/components/activity/activity-shell';

/** Placeholder for the Schedules tab — the board of what is due and when.
 *  The tab exists (and the tab bar routes to it) ahead of its contents. */
export default function ActivitySchedulesPage() {
  return (
    <ActivityShell title="Schedules" subtitle="What is due, and when.">
      <p className="text-[13px] text-[color:var(--muted-foreground)]">
        The schedule board is coming in the next change.
      </p>
    </ActivityShell>
  );
}
