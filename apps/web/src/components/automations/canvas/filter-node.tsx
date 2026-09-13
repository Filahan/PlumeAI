'use client';

import type { Node, NodeProps } from '@xyflow/react';
import { useAutomationsStore } from '@/lib/automations/store';
import NodeCard from '@/components/automations/canvas/node-card';
import NodeHandles from '@/components/automations/canvas/node-handles';
import NodeIcon from '@/components/automations/canvas/node-icon';
import { describeFilter } from '@/components/automations/canvas/describe-filter';
import {
  useStepHasIssues,
  useStepRunStatus,
  useStepSelected,
} from '@/components/automations/canvas/use-canvas-selectors';
import type { FilterNodeData } from '@/components/automations/canvas/use-auto-layout';

/** A gate rather than a doing-step, so it wears lighter chrome: a dashed card, and a
 *  subtitle that states the actual condition instead of the step type. */
export default function FilterNode({ data }: NodeProps<Node<FilterNodeData, 'filter'>>) {
  const { step, index } = data;
  const select = useAutomationsStore((s) => s.select);
  const selected = useStepSelected(step.id);
  const hasIssues = useStepHasIssues(index);
  const runStatus = useStepRunStatus(step.id);

  return (
    <>
      <NodeCard
        icon={<NodeIcon kind="filter" />}
        index={index + 1}
        title={step.name || 'Filter'}
        subtitle={`Continue only if ${describeFilter(step.settings)}`}
        selected={selected}
        onSelect={() => select({ kind: 'step', stepId: step.id })}
        needsAttention={step.valid === false || hasIssues}
        runStatus={runStatus}
        dashed
      />
      <NodeHandles />
    </>
  );
}
