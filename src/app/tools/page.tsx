'use client';

import { useRouter } from 'next/navigation';
import AppShell from '@/components/app-shell';
import ToolsView from '@/components/tools-view';
import { useConversationsStore, useSettingsStore } from '@/lib/store-provider';

export default function ToolsPage() {
  const router = useRouter();
  const { deleteConversation } = useConversationsStore();
  const { settings, setSettings } = useSettingsStore();

  return (
    <AppShell
      currentId={null}
      onSelect={(id) => router.push(`/${id}`)}
      onNewChat={() => router.push('/')}
      onDelete={(id) => deleteConversation(id)}
      leftPanel={false}
    >
      <ToolsView settings={settings} setSettings={setSettings} />
    </AppShell>
  );
}
