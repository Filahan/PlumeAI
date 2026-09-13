'use client';

import type { Node, NodeProps } from '@xyflow/react';
import { useAutomationsStore, useCatalog } from '@/lib/automations/store';
import { stepLabel } from '@/lib/automations/types';
import NodeCard from '@/components/automations/canvas/node-card';
import NodeHandles from '@/components/automations/canvas/node-handles';
import NodeIcon from '@/components/automations/canvas/node-icon';
import {
  useStepHasIssues,
  useStepRunStatus,
  useStepSelected,
} from '@/components/automations/canvas/use-canvas-selectors';
import type { StepNodeData } from '@/components/automations/canvas/use-auto-layout';

/** An action or AI step. Filters get their own chrome — see `filter-node.tsx`. */
export default function StepNode({ data }: NodeProps<Node<StepNodeData, 'step'>>) {
  const { step, index } = data;
  const catalog = useCatalog();
  const select = useAutomationsStore((s) => s.select);
  const selected = useStepSelected(step.id);
  const hasIssues = useStepHasIssues(index);
  const runStatus = useStepRunStatus(step.id);

  return (
    <>
      <NodeCard
        icon={
          <NodeIcon
            kind={step.type === 'ai' ? 'ai' : 'action'}
            integration={step.type === 'action' ? step.settings.integration : undefined}
          />
        }
        index={index + 1}
        title={step.name || 'Untitled step'}
        subtitle={stepLabel(step, catalog)}
        selected={selected}
        onSelect={() => select({ kind: 'step', stepId: step.id })}
        needsAttention={step.valid === false || hasIssues}
        runStatus={runStatus}
      />
      <NodeHandles />
    </>
  );
}
