'use client';

import type { Node, NodeProps } from '@xyflow/react';
import { Plus } from 'lucide-react';
import { useAutomationsStore } from '@/lib/automations/store';
import EmptyState from '@/components/automations/canvas/empty-state';
import NodeHandles from '@/components/automations/canvas/node-handles';
import type { AddNodeData } from '@/components/automations/canvas/use-auto-layout';

/** The permanent foot of the rail: append a step. While the automation is still empty
 *  it hands over to `EmptyState`, which says the same thing at more length. */
export default function AddNode({ data }: NodeProps<Node<AddNodeData, 'add'>>) {
  const openStepPicker = useAutomationsStore((s) => s.openStepPicker);

  return (
    <>
      <NodeHandles source={false} />
      {data.index === 0 ? (
        <EmptyState />
      ) : (
        <button
          type="button"
          onClick={() => openStepPicker(data.index)}
          className="h-full w-full rounded-2xl border border-dashed border-[color:var(--border)] bg-white text-[12px] font-medium text-[color:var(--muted-foreground)] hover:text-[color:var(--foreground)] hover:border-[color:var(--muted-foreground)]/50 hover:bg-[color:var(--surface-muted)]/60 transition inline-flex items-center justify-center gap-1.5"
        >
          <Plus size={14} strokeWidth={2.25} />
          Add step
        </button>
      )}
    </>
  );
}
