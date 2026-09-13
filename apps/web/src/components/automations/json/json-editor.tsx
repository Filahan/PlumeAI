'use client';

import { useState } from 'react';
import dynamic from 'next/dynamic';
import { json } from '@codemirror/lang-json';
import { AlertCircle, Loader2 } from 'lucide-react';
import IssuesList from '@/components/automations/issues-list';
import { useAutomationsStore, useCurrentAutomation, type CurrentAutomation } from '@/lib/automations/store';
import { prettyJson } from '@/lib/automations/format';
import type { AutomationDocument } from '@/lib/automations/types';

/** CodeMirror touches the DOM on import, so it never renders on the server. */
const CodeMirror = dynamic(() => import('@uiw/react-codemirror'), {
  ssr: false,
  loading: () => (
    <div className="h-full flex items-center justify-center text-[12px] text-[color:var(--muted-foreground)]">
      <Loader2 size={13} className="animate-spin mr-1.5" /> Loading the editor…
    </div>
  ),
});

const EXTENSIONS = [json()];

/** JSON mode: the whole document as text.
 *
 *  Typing parses continuously — a valid parse goes into the draft through `setDocument`
 *  (which debounce-validates it server-side, feeding the issue list below), an invalid
 *  one only shows the parse error and leaves the draft alone. Nothing is persisted until
 *  Apply, which is the one write that can be rejected with 422 + issues.
 *
 *  The editor is keyed on the version number, so every server acknowledgement re-seeds
 *  the text from the document that came back instead of syncing it in an effect. */
export default function JsonEditor() {
  const current = useCurrentAutomation();
  if (!current) return null;
  return <Editor key={current.versionNumber} current={current} />;
}

function Editor({ current }: { current: CurrentAutomation }) {
  const setDocument = useAutomationsStore((s) => s.setDocument);
  const saveDocument = useAutomationsStore((s) => s.saveDocument);
  // Seeded from the draft, not the saved copy, so switching Design ⇄ JSON keeps it.
  const [text, setText] = useState(() => prettyJson(current.document));
  const [parseError, setParseError] = useState<string | null>(null);

  const onChange = (next: string) => {
    setText(next);
    try {
      const parsed = JSON.parse(next) as AutomationDocument;
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        setParseError('The document must be a JSON object.');
        return;
      }
      setParseError(null);
      setDocument(parsed);
    } catch (e) {
      setParseError(e instanceof Error ? e.message : 'Invalid JSON');
    }
  };

  const cancel = () => {
    setText(prettyJson(current.savedDocument));
    setParseError(null);
    setDocument(current.savedDocument);
  };

  const blocked = parseError !== null;

  return (
    <div className="h-full min-h-0 flex flex-col">
      <div className="shrink-0 flex items-center gap-2 px-4 h-10 border-b border-[color:var(--border)] bg-white">
        <span className="text-[11px] uppercase tracking-[0.08em] text-[color:var(--muted-foreground)]">
          Document · v{current.versionNumber}
          {current.dirty && ' · unsaved'}
        </span>
        <div className="flex-1" />
        <button
          type="button"
          onClick={cancel}
          disabled={!current.dirty && !blocked}
          className="h-7 px-2.5 rounded-lg border border-[color:var(--border)] bg-white text-[11px] font-medium hover:bg-[color:var(--surface-muted)] disabled:opacity-40 transition"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={() => void saveDocument()}
          disabled={blocked || !current.dirty || current.saving}
          className="inline-flex items-center gap-1.5 h-7 px-3 rounded-lg bg-[color:var(--primary)] text-white text-[11px] font-medium hover:opacity-90 disabled:opacity-40 transition"
        >
          {current.saving && <Loader2 size={11} className="animate-spin" />}
          Apply
        </button>
      </div>

      <div className="flex-1 min-h-0 overflow-hidden bg-white">
        <CodeMirror
          value={text}
          onChange={onChange}
          extensions={EXTENSIONS}
          theme="light"
          height="100%"
          className="h-full text-[12px]"
          basicSetup={{ foldGutter: true, highlightActiveLine: false, autocompletion: false }}
        />
      </div>

      {(parseError || current.saveError || current.issues.length > 0) && (
        <div className="shrink-0 max-h-[140px] overflow-y-auto border-t border-[color:var(--border)] bg-white px-4 py-2 space-y-1">
          {parseError && <Problem text={parseError} />}
          {current.saveError && <Problem text={current.saveError} />}
          <IssuesList issues={current.issues} />
        </div>
      )}
    </div>
  );
}

function Problem({ text }: { text: string }) {
  return (
    <p className="flex items-start gap-1.5 text-[12px] text-[#D4183D]">
      <AlertCircle size={12} strokeWidth={2} className="mt-0.5 shrink-0" />
      {text}
    </p>
  );
}
