'use client';

import {
  BaseEdge,
  EdgeLabelRenderer,
  getSmoothStepPath,
  type Edge,
  type EdgeProps,
} from '@xyflow/react';
import { Plus } from 'lucide-react';
import { useAutomationsStore } from '@/lib/automations/store';
import type { AddStepEdgeData } from '@/components/automations/canvas/use-auto-layout';

/** The connector between two nodes, with the "insert here" button in its middle.
 *
 *  The button is always visible rather than hover-revealed: inserting a step between
 *  two existing ones is a first-class move, and a rail of invisible controls is not
 *  discoverable for the people this canvas is for. */
export default function AddStepEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  style,
  data,
}: EdgeProps<Edge<AddStepEdgeData, 'add-step'>>) {
  const openStepPicker = useAutomationsStore((s) => s.openStepPicker);
  const index = data?.index ?? 0;

  const [path, labelX, labelY] = getSmoothStepPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
    borderRadius: 8,
  });

  return (
    <>
      <BaseEdge id={id} path={path} style={style} />
      <EdgeLabelRenderer>
        <div
          className="nodrag nopan absolute"
          style={{ transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)` }}
        >
          <button
            type="button"
            onClick={() => openStepPicker(index)}
            aria-label={`Insert a step at position ${index + 1}`}
            title="Insert a step here"
            className="pointer-events-auto w-[22px] h-[22px] rounded-full border border-[color:var(--border)] bg-white text-[color:var(--muted-foreground)] inline-flex items-center justify-center shadow-[0_1px_2px_rgba(0,0,0,0.06)] hover:text-[color:var(--foreground)] hover:border-[color:var(--muted-foreground)]/60 transition"
          >
            <Plus size={12} strokeWidth={2.5} />
          </button>
        </div>
      </EdgeLabelRenderer>
    </>
  );
}
