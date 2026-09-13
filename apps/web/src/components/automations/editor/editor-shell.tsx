'use client';

import { useEffect } from 'react';
import { AlertCircle, Loader2 } from 'lucide-react';
import { useAutomationsStore, useCurrentAutomation } from '@/lib/automations/store';
import EditorHeader from '@/components/automations/editor/editor-header';
import AutomationCanvas from '@/components/automations/canvas/automation-canvas';
import InspectorPanel from '@/components/automations/inspector/inspector-panel';
import JsonEditor from '@/components/automations/json/json-editor';
import RunPanel from '@/components/automations/runs/run-panel';
import IssuesList from '@/components/automations/issues-list';

/** The automation editor.
 *
 *  Layout: header · body (canvas + inspector, or the JSON view) · run panel. The whole
 *  thing is driven by `store.current`, loaded here on mount and torn down on unmount —
 *  which also stops any live run stream. */
export default function EditorShell({ id }: { id: string }) {
  const open = useAutomationsStore((s) => s.open);
  const close = useAutomationsStore((s) => s.close);
  const loadCatalog = useAutomationsStore((s) => s.loadCatalog);
  const loading = useAutomationsStore((s) => s.currentLoading);
  const error = useAutomationsStore((s) => s.currentError);
  const current = useCurrentAutomation();

  useEffect(() => {
    void open(id);
    void loadCatalog();
    return () => close();
  }, [id, open, close, loadCatalog]);

  if (error) {
    return (
      <div className="flex-1 flex items-center justify-center p-8">
        <p className="flex items-center gap-1.5 text-[13px] text-[#D4183D]">
          <AlertCircle size={14} strokeWidth={2} /> {error}
        </p>
      </div>
    );
  }

  if (!current) {
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
      <EditorHeader current={current} />

      {current.saveError && (
        <div className="shrink-0 px-4 py-2 border-b border-[color:var(--border)] bg-[#D4183D]/5">
          <p className="flex items-center gap-1.5 text-[12px] text-[#D4183D]">
            <AlertCircle size={13} strokeWidth={2} /> {current.saveError}
          </p>
        </div>
      )}

      <div className="flex-1 min-h-0 flex">
        {current.mode === 'design' ? (
          <>
            <div className="flex-1 min-w-0 flex flex-col">
              <div className="flex-1 min-h-0">
                <AutomationCanvas />
              </div>
              {current.issues.length > 0 && (
                <div className="shrink-0 max-h-[96px] overflow-y-auto border-t border-[color:var(--border)] bg-white px-4 py-2">
                  <IssuesList issues={current.issues} />
                </div>
              )}
            </div>
            {current.inspectorOpen && <InspectorPanel />}
          </>
        ) : (
          <div className="flex-1 min-w-0 min-h-0">
            <JsonEditor />
          </div>
        )}
      </div>

      <RunPanel />
    </div>
  );
}
