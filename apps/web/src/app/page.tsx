'use client';

import { useRouter } from 'next/navigation';
import AppShell from '@/components/app-shell';
import { AutomationsSidebar } from '@/components/automations/list/automations-sidebar';
import AutomationsHome from '@/components/automations/home/automations-home';
import { useConversationsStore } from '@/lib/store-provider';

/** `/` — automations home. The chat lives at `/chat`. */
export default function Home() {
  const router = useRouter();
  const { deleteConversation } = useConversationsStore();

  return (
    <AppShell
      currentId={null}
      onSelect={(id) => router.push(`/chat/${id}`)}
      onNewChat={() => router.push('/chat')}
      onDelete={(id) => deleteConversation(id)}
      leftPanel={<AutomationsSidebar />}
    >
      <AutomationsHome />
    </AppShell>
  );
}
