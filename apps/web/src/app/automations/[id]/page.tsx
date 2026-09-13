'use client';

import { use, useState } from 'react';
import { useRouter } from 'next/navigation';
import AppShell from '@/components/app-shell';
import { AutomationsSidebar } from '@/components/automations/list/automations-sidebar';
import EditorShell from '@/components/automations/editor/editor-shell';
import { useConversationsStore } from '@/lib/store-provider';

export default function AutomationEditorPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const router = useRouter();
  const { deleteConversation } = useConversationsStore();
  // Controlled so the assistant drawer can point at a missing API key (same pattern as
  // the chat composer's missing-key notice).
  const [settingsOpen, setSettingsOpen] = useState(false);

  return (
    <AppShell
      currentId={null}
      onSelect={(cid) => router.push(`/chat/${cid}`)}
      onNewChat={() => router.push('/chat')}
      onDelete={(cid) => deleteConversation(cid)}
      leftPanel={<AutomationsSidebar />}
      settingsOpen={settingsOpen}
      onSettingsOpenChange={setSettingsOpen}
    >
      <EditorShell id={id} onOpenSettings={() => setSettingsOpen(true)} />
    </AppShell>
  );
}
