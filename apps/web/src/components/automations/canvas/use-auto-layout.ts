'use client';

/** Auto-layout for the automation canvas.
 *
 *  The canvas is deliberately *not* a freeform graph editor: an automation is a linear
 *  list of steps, so there is nothing for a user to position. Every render derives the
 *  whole graph from the document — a trigger node on top, one node per step, and a
 *  trailing "add" node — and dagre (`rankdir: TB`) assigns the coordinates. Nodes are
 *  never draggable, which means the layout is always the single source of truth.
 *
 *  `layoutDocument` is pure (no React, no store): given a document it returns the exact
 *  nodes and edges React Flow should render. Sanity-checkable by hand:
 *
 *    layoutDocument({...doc, steps: []})        → 2 nodes  (trigger, add), 1 edge
 *    layoutDocument({...doc, steps: [a, b]})    → 4 nodes, 3 edges; the edge into `a`
 *                                                 carries index 0, the one into `b`
 *                                                 index 1, and the tail edge is plain
 *    insertionIndexForEdge('b', ['a','b'])      → 1
 *    insertionIndexForEdge(ADD_NODE_ID, [...])  → steps.length
 */

import { useMemo } from 'react';
import dagre from '@dagrejs/dagre';
import { Position, type Edge, type Node } from '@xyflow/react';
import type {
  AutomationDocument,
  AutomationStep,
  FilterStep,
  Trigger,
} from '@/lib/automations/types';

// ─── Geometry ───────────────────────────────────────────────────────────────────────

export const NODE_WIDTH = 320;
export const NODE_HEIGHT = 72;
/** The trailing "+ Add step" card. */
export const ADD_NODE_HEIGHT = 44;
/** …which grows into the empty-state card while the automation has no steps. */
export const EMPTY_NODE_HEIGHT = 148;
export const NODE_SEP = 40;
export const RANK_SEP = 64;

/** Reserved node ids — step ids are always `step_…`, so these can never collide. */
export const TRIGGER_NODE_ID = '__trigger';
export const ADD_NODE_ID = '__add';

// ─── Node / edge payloads ───────────────────────────────────────────────────────────
// Object *type aliases* (not interfaces) so they satisfy React Flow's
// `Record<string, unknown>` constraint on node data.

export type TriggerNodeData = { trigger: Trigger };
export type StepNodeData = { step: AutomationStep; index: number };
export type FilterNodeData = { step: FilterStep; index: number };
export type AddNodeData = { index: number };
/** The insertion index the edge's "+" button applies. */
export type AddStepEdgeData = { index: number };

export type TriggerFlowNode = Node<TriggerNodeData, 'trigger'>;
export type StepFlowNode = Node<StepNodeData, 'step'>;
export type FilterFlowNode = Node<FilterNodeData, 'filter'>;
export type AddFlowNode = Node<AddNodeData, 'add'>;

export interface AutomationLayout {
  nodes: Node[];
  edges: Edge[];
}

export interface LayoutOptions {
  nodeWidth?: number;
  nodeHeight?: number;
  nodeSep?: number;
  rankSep?: number;
}

const EDGE_STYLE = {
  stroke: 'var(--muted-foreground)',
  strokeWidth: 1.5,
  strokeOpacity: 0.45,
} as const;

const EMPTY_LAYOUT: AutomationLayout = { nodes: [], edges: [] };

// ─── Helpers ────────────────────────────────────────────────────────────────────────

/** Where a step dropped on the edge *entering* `targetId` lands in `doc.steps`.
 *  The edge into step `i` inserts at `i` (pushing that step down); the tail edge into
 *  the add node appends. Unknown targets append too, which keeps the UI harmless if the
 *  graph and the document ever disagree. */
export function insertionIndexForEdge(targetId: string, stepIds: readonly string[]): number {
  if (targetId === ADD_NODE_ID) return stepIds.length;
  const index = stepIds.indexOf(targetId);
  return index < 0 ? stepIds.length : index;
}

function edgeId(source: string, target: string): string {
  return `e:${source}->${target}`;
}

// ─── Layout ─────────────────────────────────────────────────────────────────────────

export function layoutDocument(
  doc: AutomationDocument,
  opts: LayoutOptions = {}
): AutomationLayout {
  const width = opts.nodeWidth ?? NODE_WIDTH;
  const height = opts.nodeHeight ?? NODE_HEIGHT;
  const steps = doc.steps;
  const stepIds = steps.map((s) => s.id);
  const empty = steps.length === 0;

  const sizes = new Map<string, { width: number; height: number }>();
  sizes.set(TRIGGER_NODE_ID, { width, height });
  for (const id of stepIds) sizes.set(id, { width, height });
  sizes.set(ADD_NODE_ID, { width, height: empty ? EMPTY_NODE_HEIGHT : ADD_NODE_HEIGHT });

  const rail = [TRIGGER_NODE_ID, ...stepIds, ADD_NODE_ID];

  const graph = new dagre.graphlib.Graph();
  graph.setGraph({
    rankdir: 'TB',
    nodesep: opts.nodeSep ?? NODE_SEP,
    ranksep: opts.rankSep ?? RANK_SEP,
    marginx: 32,
    marginy: 32,
  });
  graph.setDefaultEdgeLabel(() => ({}));
  for (const id of rail) graph.setNode(id, { ...(sizes.get(id) ?? { width, height }) });
  for (let i = 0; i < rail.length - 1; i += 1) graph.setEdge(rail[i], rail[i + 1]);
  dagre.layout(graph);

  /** dagre reports centers; React Flow wants the top-left corner. */
  const positionOf = (id: string): { x: number; y: number } => {
    const laid = graph.node(id) as { x?: number; y?: number } | undefined;
    const size = sizes.get(id) ?? { width, height };
    return {
      x: (laid?.x ?? 0) - size.width / 2,
      y: (laid?.y ?? 0) - size.height / 2,
    };
  };

  const base = {
    draggable: false,
    sourcePosition: Position.Bottom,
    targetPosition: Position.Top,
  } as const;

  const nodes: Node[] = [
    {
      ...base,
      id: TRIGGER_NODE_ID,
      type: 'trigger',
      position: positionOf(TRIGGER_NODE_ID),
      data: { trigger: doc.trigger } satisfies TriggerNodeData,
      width,
      height,
    } satisfies TriggerFlowNode,
  ];

  steps.forEach((step, index) => {
    const shared = { ...base, id: step.id, position: positionOf(step.id), width, height };
    nodes.push(
      step.type === 'filter'
        ? ({
            ...shared,
            type: 'filter',
            data: { step, index } satisfies FilterNodeData,
          } satisfies FilterFlowNode)
        : ({
            ...shared,
            type: 'step',
            data: { step, index } satisfies StepNodeData,
          } satisfies StepFlowNode)
    );
  });

  nodes.push({
    ...base,
    id: ADD_NODE_ID,
    type: 'add',
    position: positionOf(ADD_NODE_ID),
    data: { index: steps.length } satisfies AddNodeData,
    width,
    height: empty ? EMPTY_NODE_HEIGHT : ADD_NODE_HEIGHT,
    selectable: false,
  } satisfies AddFlowNode);

  const edges: Edge[] = [];
  for (let i = 0; i < rail.length - 1; i += 1) {
    const source = rail[i];
    const target = rail[i + 1];
    // The tail edge needs no "+": the add node it points at *is* the affordance.
    const plain = target === ADD_NODE_ID;
    edges.push({
      id: edgeId(source, target),
      source,
      target,
      type: plain ? 'smoothstep' : 'add-step',
      style: EDGE_STYLE,
      // The rail is not editable by hand: an edge is never a thing to select.
      selectable: false,
      focusable: false,
      ...(plain ? {} : { data: { index: insertionIndexForEdge(target, stepIds) } }),
    });
  }

  return { nodes, edges };
}

/** Memoized `layoutDocument`. The document is replaced wholesale on every write, so
 *  identity is a correct (and cheap) cache key. */
export function useAutoLayout(doc: AutomationDocument | null): AutomationLayout {
  return useMemo(() => (doc ? layoutDocument(doc) : EMPTY_LAYOUT), [doc]);
}
