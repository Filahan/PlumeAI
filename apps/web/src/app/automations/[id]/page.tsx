'use client';

import { use, useState } from 'react';
import AppShell from '@/components/app-shell';
import { AutomationsSidebar } from '@/components/automations/list/automations-sidebar';
import EditorShell from '@/components/automations/editor/editor-shell';
import StepDeepLink from '@/components/automations/editor/step-deep-link';

export default function AutomationEditorPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  // Controlled so the assistant drawer can point at a missing API key.
  const [settingsOpen, setSettingsOpen] = useState(false);

  return (
    <AppShell
      leftPanel={<AutomationsSidebar />}
      settingsOpen={settingsOpen}
      onSettingsOpenChange={setSettingsOpen}
    >
      {/* `?step=` arrives from a failed run's "Fix this field". */}
      <StepDeepLink automationId={id} />
      <EditorShell id={id} onOpenSettings={() => setSettingsOpen(true)} />
    </AppShell>
  );
}
