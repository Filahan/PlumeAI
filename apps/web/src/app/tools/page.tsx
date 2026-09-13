'use client';

import AppShell from '@/components/app-shell';
import ToolsView from '@/components/tools-view';
import { useSettingsStore } from '@/lib/store-provider';

export default function ToolsPage() {
  const { settings, setSettings } = useSettingsStore();

  return (
    <AppShell>
      <ToolsView settings={settings} setSettings={setSettings} />
    </AppShell>
  );
}
