'use client';

import AppShell from '@/components/app-shell';
import { AutomationsSidebar } from '@/components/automations/list/automations-sidebar';
import AutomationsHome from '@/components/automations/home/automations-home';

/** `/` — automations home: the list in the left panel, the "what should it do?" prompt
 *  in the main area. */
export default function Home() {
  return (
    <AppShell leftPanel={<AutomationsSidebar />}>
      <AutomationsHome />
    </AppShell>
  );
}
