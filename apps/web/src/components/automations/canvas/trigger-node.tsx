'use client';

import type { Node, NodeProps } from '@xyflow/react';
import { useAutomationsStore } from '@/lib/automations/store';
import { capitalize, describeTrigger, triggerTimezone } from '@/lib/automations/types';
import NodeCard from '@/components/automations/canvas/node-card';
import NodeHandles from '@/components/automations/canvas/node-handles';
import NodeIcon from '@/components/automations/canvas/node-icon';
import { useTriggerSelected } from '@/components/automations/canvas/use-canvas-selectors';
import type { TriggerNodeData } from '@/components/automations/canvas/use-auto-layout';

/** Top of the rail: when the automation runs. */
export default function TriggerNode({ data }: NodeProps<Node<TriggerNodeData, 'trigger'>>) {
  const select = useAutomationsStore((s) => s.select);
  const selected = useTriggerSelected();
  const timezone = triggerTimezone(data.trigger);

  return (
    <>
      <NodeCard
        icon={<NodeIcon kind="trigger" />}
        title="Trigger"
        subtitle={`${capitalize(describeTrigger(data.trigger))}${timezone ? ` (${timezone})` : ''}`}
        selected={selected}
        onSelect={() => select({ kind: 'trigger' })}
      />
      <NodeHandles target={false} />
    </>
  );
}
