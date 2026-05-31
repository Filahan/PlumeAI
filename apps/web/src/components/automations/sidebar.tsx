'use client';

import { Task } from '@/lib/types';
import { TaskList } from '@/components/automations/view';
import { Plus } from 'lucide-react';

export function AutomationsSidebar({
  tasks, tasksLoaded, selectedTaskId, onSelectTask, onNewTask, onDeleteTask,
}: {
  tasks: Task[];
  tasksLoaded: boolean;
  selectedTaskId: string | null;
  onSelectTask: (id: string) => void;
  onNewTask: () => void;
  onDeleteTask: (id: string) => void;
}) {
  return (
    <aside className="w-[260px] shrink-0 h-full flex flex-col bg-[color:var(--surface-muted)] border-r border-[color:var(--border)]">
      <div className="flex items-center justify-between px-4 pt-4 pb-1">
        <span className="text-[11px] font-semibold tracking-[0.08em] uppercase text-[color:var(--muted-foreground)]">
          Tasks
        </span>
        <button
          type="button"
          onClick={onNewTask}
          aria-label="New task"
          className="h-6 w-6 inline-flex items-center justify-center rounded-md text-[color:var(--muted-foreground)] hover:bg-white hover:text-[color:var(--foreground)] transition"
        >
          <Plus size={15} strokeWidth={2} />
        </button>
      </div>

      <TaskList
        tasks={tasks}
        loaded={tasksLoaded}
        selectedId={selectedTaskId}
        onSelect={onSelectTask}
        onDelete={onDeleteTask}
      />
    </aside>
  );
}
