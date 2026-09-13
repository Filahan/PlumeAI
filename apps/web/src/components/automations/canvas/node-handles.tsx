'use client';

import { Handle, Position } from '@xyflow/react';

const HIDDEN = { opacity: 0, pointerEvents: 'none' } as const;

/** Anchor points the edges attach to. The rail is fixed, so they are invisible and
 *  inert — nothing on this canvas is hand-connected. */
export default function NodeHandles({
  target = true,
  source = true,
}: {
  target?: boolean;
  source?: boolean;
}) {
  return (
    <>
      {target && (
        <Handle type="target" position={Position.Top} isConnectable={false} style={HIDDEN} />
      )}
      {source && (
        <Handle type="source" position={Position.Bottom} isConnectable={false} style={HIDDEN} />
      )}
    </>
  );
}
