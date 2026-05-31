'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import AppShell from '@/components/app-shell';
import AutomationsView from '@/components/automations/view';
import { AutomationsSidebar } from '@/components/automations/sidebar';
import { useConversationsStore, useSettingsStore } from '@/lib/store-provider';
import { useAutomations } from '@/lib/hooks/use-automations';

export default function AutomationsPage() {
  const router = useRouter();
  const { deleteConversation } = useConversationsStore();
  const { settings } = useSettingsStore();
  const automations = useAutomations();

  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const selectedTask = automations.tasks.find((t) => t.id === selectedTaskId) ?? null;

  return (
    <AppShell
      currentId={null}
      onSelect={(id) => router.push(`/${id}`)}
      onNewChat={() => router.push('/')}
      onDelete={(id) => deleteConversation(id)}
      leftPanel={
        <AutomationsSidebar
          tasks={automations.tasks}
          tasksLoaded={automations.loaded}
          selectedTaskId={selectedTaskId}
          onSelectTask={setSelectedTaskId}
          onNewTask={() => setSelectedTaskId(null)}
          onDeleteTask={(id) => {
            automations.deleteTask(id);
            if (id === selectedTaskId) setSelectedTaskId(null);
          }}
        />
      }
    >
      <AutomationsView
        settings={settings}
        selected={selectedTask}
        automations={automations}
        onSelect={setSelectedTaskId}
      />
    </AppShell>
  );
}
