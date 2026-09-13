'use client';

import '@xyflow/react/dist/style.css';

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from 'react';
import {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  Panel,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type EdgeTypes,
  type NodeTypes,
} from '@xyflow/react';
import { useAutomationsStore } from '@/lib/automations/store';
import StepPickerDialog from '@/components/automations/step-picker/step-picker-dialog';
import AddNode from '@/components/automations/canvas/add-node';
import AddStepEdge from '@/components/automations/canvas/add-step-edge';
import FilterNode from '@/components/automations/canvas/filter-node';
import StepNode from '@/components/automations/canvas/step-node';
import TriggerNode from '@/components/automations/canvas/trigger-node';
import { useAutoLayout } from '@/components/automations/canvas/use-auto-layout';

/** Stable across renders — React Flow warns (and remounts every node) otherwise. */
const NODE_TYPES: NodeTypes = {
  trigger: TriggerNode,
  step: StepNode,
  filter: FilterNode,
  add: AddNode,
};

const EDGE_TYPES: EdgeTypes = { 'add-step': AddStepEdge };

const FIT_VIEW = { padding: 0.2, maxZoom: 1, duration: 220 };
/** Above this, the rail is longer than a screen and an overview starts to pay off. */
const MINIMAP_THRESHOLD = 6;
const CONFIRM_MS = 2000;

function isTypingTarget(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el) return false;
  if (el.isContentEditable) return true;
  return el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT';
}

function Canvas() {
  // Field-level selectors on purpose: a live run pushes `step_text` deltas into
  // `current` several times a second, and the canvas must not relayout on each one.
  const doc = useAutomationsStore((s) => s.current?.document ?? null);
  const applyOperations = useAutomationsStore((s) => s.applyOperations);
  const select = useAutomationsStore((s) => s.select);
  const closeStepPicker = useAutomationsStore((s) => s.closeStepPicker);
  const picker = useAutomationsStore((s) => s.stepPicker);

  const { nodes, edges } = useAutoLayout(doc);
  const stepCount = doc?.steps.length ?? 0;

  const { fitView } = useReactFlow();

  /** Keyboard scope. The delete shortcut used to live on `window`, which meant a
   *  Backspace in the inspector — or in any open dialog — could remove the selected
   *  step. Now it only fires while this wrapper (or something inside it) has focus. */
  const wrapperRef = useRef<HTMLDivElement | null>(null);

  /** Delete is destructive and un-undoable, so it arms first: the second press within
   *  two seconds removes the step (the same confirm-in-place the sidebar uses). */
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const pendingRef = useRef<string | null>(null);
  const timerRef = useRef<number | undefined>(undefined);

  const disarm = useCallback(() => {
    pendingRef.current = null;
    setPendingDelete(null);
    window.clearTimeout(timerRef.current);
  }, []);

  const arm = useCallback((stepId: string) => {
    pendingRef.current = stepId;
    setPendingDelete(stepId);
    window.clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(() => {
      pendingRef.current = null;
      setPendingDelete(null);
    }, CONFIRM_MS);
  }, []);

  useEffect(() => () => window.clearTimeout(timerRef.current), []);

  // The picker lives in the store, so make sure it never survives this canvas.
  useEffect(() => closeStepPicker, [closeStepPicker]);

  // Re-frame on open and whenever the rail grows or shrinks.
  useEffect(() => {
    const handle = window.setTimeout(() => void fitView(FIT_VIEW), 0);
    return () => window.clearTimeout(handle);
  }, [fitView, stepCount]);

  /** Node cards are real buttons, so a click usually focuses one of them — already
   *  inside the wrapper, so the shortcut works and the focus ring stays where the user
   *  clicked. Some browsers don't focus buttons on click; take the wrapper then. */
  const focusCanvas = useCallback(() => {
    const wrapper = wrapperRef.current;
    if (!wrapper) return;
    if (!wrapper.contains(document.activeElement)) wrapper.focus();
  }, []);

  const onKeyDown = useCallback(
    (event: ReactKeyboardEvent<HTMLDivElement>) => {
      if (isTypingTarget(event.target)) return;
      const state = useAutomationsStore.getState();
      if (state.stepPicker.open) return;

      if (event.key === 'Escape') {
        disarm();
        state.select(null);
        return;
      }
      if (event.key !== 'Delete' && event.key !== 'Backspace') return;

      const selection = state.current?.selection;
      if (selection?.kind !== 'step') return;
      event.preventDefault();

      if (pendingRef.current !== selection.stepId) {
        arm(selection.stepId);
        return;
      }
      disarm();
      void applyOperations([{ op: 'remove_step', step_id: selection.stepId }])
        .then(() => state.select(null))
        .catch(() => {
          // `current.saveError` carries the reason; the shell shows it.
        });
    },
    [applyOperations, arm, disarm]
  );

  const pendingName = useMemo(
    () => doc?.steps.find((s) => s.id === pendingDelete)?.name ?? null,
    [doc, pendingDelete]
  );

  if (!doc) return null;

  return (
    <div
      ref={wrapperRef}
      tabIndex={-1}
      onKeyDown={onKeyDown}
      className="h-full w-full bg-[color:var(--surface-muted)]/40 outline-none"
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={NODE_TYPES}
        edgeTypes={EDGE_TYPES}
        nodesDraggable={false}
        nodesConnectable={false}
        nodesFocusable={false}
        onNodeClick={() => focusCanvas()}
        onPaneClick={() => {
          disarm();
          select(null);
        }}
        panOnScroll
        panOnDrag
        zoomOnScroll={false}
        zoomOnDoubleClick={false}
        zoomOnPinch
        minZoom={0.4}
        maxZoom={1.6}
        fitView
        fitViewOptions={FIT_VIEW}
        deleteKeyCode={null}
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={18} size={1} color="var(--border)" />
        <Controls showInteractive={false} position="bottom-right" />
        {nodes.length > MINIMAP_THRESHOLD && (
          <MiniMap
            pannable
            zoomable
            position="top-right"
            nodeColor="var(--border)"
            maskColor="rgba(247, 246, 250, 0.7)"
          />
        )}
        {pendingDelete && (
          <Panel position="bottom-center">
            <div className="mb-2 rounded-xl border border-[color:var(--border)] bg-white px-3 py-1.5 text-[12px] shadow-[0_1px_3px_rgba(0,0,0,0.08)]">
              Press <kbd className="font-medium">Delete</kbd> again to remove
              {pendingName ? ` “${pendingName}”` : ' this step'}
            </div>
          </Panel>
        )}
      </ReactFlow>

      <StepPickerDialog
        open={picker.open}
        index={picker.index}
        onOpenChange={(open) => {
          if (!open) closeStepPicker();
        }}
      />
    </div>
  );
}

/** The automation canvas: a vertical rail of nodes laid out from the document.
 *
 *  There is no manual positioning and no free-form connecting — an automation *is* an
 *  ordered list, so the graph is regenerated from the document on every change and
 *  dagre places it. All the canvas owns is viewport state; everything else is read from
 *  (and written back to) the store. */
export default function AutomationCanvas() {
  return (
    <ReactFlowProvider>
      <Canvas />
    </ReactFlowProvider>
  );
}
