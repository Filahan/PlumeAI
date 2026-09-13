'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import AppShell from '@/components/app-shell';
import AutomationsView from '@/components/automations/view';
import { AutomationsSidebar } from '@/components/automations/sidebar';
import { useConversationsStore } from '@/lib/store-provider';
import { useAutomations } from '@/lib/hooks/use-automations';

export default function AutomationsPage() {
  const router = useRouter();
  const { deleteConversation } = useConversationsStore();
  const automations = useAutomations();

  const [selectedId, setSelectedId] = useState<string | null>(null);

  const createAndSelect = async () => {
    try {
      const id = await automations.create('New automation');
      setSelectedId(id);
    } catch {
      // error surfaced via automations.error
    }
  };

  return (
    <AppShell
      currentId={null}
      onSelect={(id) => router.push(`/${id}`)}
      onNewChat={() => router.push('/')}
      onDelete={(id) => deleteConversation(id)}
      leftPanel={
        <AutomationsSidebar
          automations={automations.automations}
          loaded={automations.loaded}
          selectedId={selectedId}
          onSelect={setSelectedId}
          onNew={() => void createAndSelect()}
          onDelete={(id) => {
            void automations.remove(id);
            if (id === selectedId) setSelectedId(null);
          }}
        />
      }
    >
      <AutomationsView selectedId={selectedId} automations={automations} />
    </AppShell>
  );
}
