'use client';

import { useEffect } from 'react';
import { AlertCircle, Loader2 } from 'lucide-react';
import {
  useAutomationsStore,
  useEditorIssues,
  useEditorSaveErrorIssues,
} from '@/lib/automations/store';
import EditorHeader from '@/components/automations/editor/editor-header';
import AutomationCanvas from '@/components/automations/canvas/automation-canvas';
import InspectorPanel from '@/components/automations/inspector/inspector-panel';
import JsonEditor from '@/components/automations/json/json-editor';
import RunPanel from '@/components/automations/runs/run-panel';
import AssistantDrawer from '@/components/automations/assistant/assistant-drawer';
import IssuesList from '@/components/automations/issues-list';

/** The automation editor.
 *
 *  Layout: header · body (canvas + inspector, or the JSON view) · run panel. The
 *  assistant drawer takes the inspector's slot when it is open. The whole thing is
 *  driven by `store.current`, loaded here on mount and torn down on unmount — which
 *  also stops any live run stream.
 *
 *  Every read below is a single field rather than `current`: a streaming run pushes a
 *  `step_text` delta into the slice several times a second, and subscribing to the whole
 *  object would re-render the editor (canvas included) on each one. */
export default function EditorShell({
  id,
  onOpenSettings,
}: {
  id: string;
  /** Opens the Settings dialog (owned by the shell) — the assistant needs it to point
   *  at the missing API key. */
  onOpenSettings?: () => void;
}) {
  const open = useAutomationsStore((s) => s.open);
  const close = useAutomationsStore((s) => s.close);
  const loadCatalog = useAutomationsStore((s) => s.loadCatalog);
  const loading = useAutomationsStore((s) => s.currentLoading);
  const error = useAutomationsStore((s) => s.currentError);

  const ready = useAutomationsStore((s) => s.current !== null);
  const mode = useAutomationsStore((s) => s.current?.mode ?? 'design');
  const inspectorOpen = useAutomationsStore((s) => s.current?.inspectorOpen ?? false);
  const assistantOpen = useAutomationsStore((s) => s.current?.assistantOpen ?? false);
  const sendAssistantMessage = useAutomationsStore((s) => s.sendAssistantMessage);
  const consumeAssistantFirstMessage = useAutomationsStore((s) => s.consumeAssistantFirstMessage);
  const saveError = useAutomationsStore((s) => s.current?.saveError ?? null);
  const saveErrorDetail = useAutomationsStore((s) => s.current?.saveErrorDetail ?? null);
  const saveErrorIssues = useEditorSaveErrorIssues();
  const issues = useEditorIssues();

  useEffect(() => {
    void open(id);
    void loadCatalog();
    return () => close();
  }, [id, open, close, loadCatalog]);

  // The home page's "describe what you want" box hands its text over through the store;
  // send it as the first message once the automation is actually loaded. Consuming it
  // clears it, so this fires exactly once.
  useEffect(() => {
    if (!ready) return;
    const first = consumeAssistantFirstMessage(id);
    if (first) void sendAssistantMessage(first);
  }, [id, ready, consumeAssistantFirstMessage, sendAssistantMessage]);

  if (error) {
    return (
      <div className="flex-1 flex items-center justify-center p-8">
        <p className="flex items-center gap-1.5 text-[13px] text-[#D4183D]">
          <AlertCircle size={14} strokeWidth={2} /> {error}
        </p>
      </div>
    );
  }

  if (!ready) {
    return (
      <div className="flex-1 flex items-center justify-center p-8">
        {loading && (
          <span className="flex items-center gap-1.5 text-[13px] text-[color:var(--muted-foreground)]">
            <Loader2 size={14} className="animate-spin" /> Loading…
          </span>
        )}
      </div>
    );
  }

  return (
    <div className="flex-1 min-h-0 flex flex-col">
      <EditorHeader />

      {saveError && (
        <div className="shrink-0 px-4 py-2 border-b border-[color:var(--border)] bg-[#D4183D]/5">
          <p className="flex items-center gap-1.5 text-[12px] text-[#D4183D]">
            <AlertCircle size={13} strokeWidth={2} className="shrink-0" /> {saveError}
          </p>
          {/* Per-field problems the rejected write itself raised — they point into the
              payload, so they belong here rather than in the document's issue list. */}
          {saveErrorIssues.length > 0 && (
            <IssuesList issues={saveErrorIssues} className="mt-1 pl-[18px]" />
          )}
          {/* The server's own wording is often a multi-line Pydantic report — useful,
              but not at the top of the editor. */}
          {saveErrorDetail && saveErrorDetail !== saveError && (
            <details className="mt-1">
              <summary className="cursor-pointer text-[11px] text-[color:var(--muted-foreground)] hover:text-[color:var(--foreground)]">
                Details
              </summary>
              <pre className="mt-1 max-h-[120px] overflow-auto whitespace-pre-wrap break-words font-mono text-[11px] leading-snug text-[color:var(--muted-foreground)]">
                {saveErrorDetail}
              </pre>
            </details>
          )}
        </div>
      )}

      <div className="flex-1 min-h-0 flex">
        {mode === 'design' ? (
          <>
            <div className="flex-1 min-w-0 flex flex-col">
              <div className="flex-1 min-h-0">
                <AutomationCanvas />
              </div>
              {issues.length > 0 && (
                <div className="shrink-0 max-h-[96px] overflow-y-auto border-t border-[color:var(--border)] bg-white px-4 py-2">
                  <IssuesList issues={issues} />
                </div>
              )}
            </div>
            {inspectorOpen && !assistantOpen && <InspectorPanel />}
          </>
        ) : (
          <div className="flex-1 min-w-0 min-h-0">
            <JsonEditor />
          </div>
        )}
        {assistantOpen && <AssistantDrawer onOpenSettings={onOpenSettings} />}
      </div>

      <RunPanel />
    </div>
  );
}
