'use client';

import { use } from 'react';
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

  return (
    <AppShell
      currentId={null}
      onSelect={(cid) => router.push(`/chat/${cid}`)}
      onNewChat={() => router.push('/chat')}
      onDelete={(cid) => deleteConversation(cid)}
      leftPanel={<AutomationsSidebar />}
    >
      <EditorShell id={id} />
    </AppShell>
  );
}
