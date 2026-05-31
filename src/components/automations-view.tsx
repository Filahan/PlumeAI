'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Provider, Settings, Task, TaskStatus, TaskSchedule, ToolStep, InterviewMessage,
  PROVIDER_MODELS, PROVIDER_NAMES, PROVIDER_ACCENT, TASK_SCHEDULE_LABELS, findApiKey,
} from '@/lib/types';
import type { useAutomations } from '@/lib/use-automations';
import { MarkdownRenderer } from '@/components/markdown-renderer';
import { ProviderLogo } from '@/components/provider-logo';
import MentionAutocomplete, { type MentionAutocompleteHandle } from '@/components/mention-autocomplete';
import { TOOL_DESCRIPTORS } from '@/lib/tools/registry-client';
import {
  Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectSeparator, SelectTrigger,
} from '@/components/ui/select';
import {
  Play, Square, Trash2, Loader2, Workflow, Clock, AlertCircle, Check,
  Search, Globe, Send, Wrench, MessageSquare,
} from 'lucide-react';

type AutomationsApi = ReturnType<typeof useAutomations>;

const SCHEDULES: TaskSchedule[] = ['manual', 'hourly', 'daily', 'weekly'];

const STARTER_PROMPTS: readonly string[] = [
  'Summarize my Gmail inbox for today',
  'Daily Hacker News top 5 stories',
  'Fetch a URL daily and email me a summary',
] as const;

export const TASK_STATUS_DOT: Record<TaskStatus, string> = {
  idle: 'bg-[color:var(--muted-foreground)]/40',
  running: 'bg-[#6366f1]',
  succeeded: 'bg-[#10A37F]',
  failed: 'bg-[#D4183D]',
  cancelled: 'bg-[color:var(--muted-foreground)]/40',
};

export function taskLabel(task: Pick<Task, 'title' | 'prompt' | 'messages'>): string {
  if (task.title && task.title.trim()) return task.title.trim();
  const firstUserMsg = task.messages.find((m) => m.role === 'user')?.content;
  const source = firstUserMsg || task.prompt;
  const firstLine = source.trim().split('\n')[0];
  return firstLine.slice(0, 60) || 'Untitled task';
}

/* ─────────────────────────── Task list (left-panel rows) ─────────────────────────── */

export function TaskList({
  tasks, loaded, selectedId, onSelect, onDelete,
}: {
  tasks: Task[];
  loaded: boolean;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);

  return (
    <div className="flex-1 overflow-y-auto px-2 pb-3">
      {!loaded ? null : tasks.length === 0 ? (
        <p className="px-3 py-2 text-[12px] text-[color:var(--muted-foreground)]">No tasks yet</p>
      ) : (
        tasks.map((t) => {
          const isActive = t.id === selectedId;
          return (
            <div
              key={t.id}
              className={`group relative rounded-lg transition-colors ${
                isActive ? 'bg-white shadow-[0_1px_2px_rgba(0,0,0,0.04)]' : 'hover:bg-white/60'
              }`}
            >
              <button
                type="button"
                onClick={() => onSelect(t.id)}
                className="w-full text-left px-3 py-2 pr-9 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--ring)]"
              >
                <div className="flex items-center gap-1.5">
                  <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${TASK_STATUS_DOT[t.status]}`} />
                  <span className={`truncate text-[13px] ${isActive ? 'font-medium' : ''}`}>{taskLabel(t)}</span>
                </div>
                <div className="mt-1 flex items-center gap-1 text-[11px] text-[color:var(--muted-foreground)]">
                  <Clock size={11} strokeWidth={1.75} />
                  {TASK_SCHEDULE_LABELS[t.schedule]}
                </div>
              </button>
              {pendingDelete === t.id ? (
                <button
                  type="button"
                  onClick={() => { onDelete(t.id); setPendingDelete(null); }}
                  className="absolute right-1.5 top-2 h-7 px-2 inline-flex items-center justify-center rounded-md bg-red-600 text-white text-[11px] font-medium hover:bg-red-700 transition"
                >
                  Delete?
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() => setPendingDelete(t.id)}
                  aria-label="Delete task"
                  className="absolute right-1.5 top-2 h-7 w-7 inline-flex items-center justify-center rounded-md text-[color:var(--muted-foreground)] hover:bg-[color:var(--surface-muted)] hover:text-red-600 opacity-0 group-hover:opacity-100 focus-visible:opacity-100 transition"
                >
                  <Trash2 size={13} strokeWidth={1.75} />
                </button>
              )}
            </div>
          );
        })
      )}
    </div>
  );
}

/* ─────────────────────────── Main view (tasks) ─────────────────────────── */

export default function AutomationsView({
  settings, selected, automations, onSelect,
}: {
  settings: Settings;
  selected: Task | null;
  automations: AutomationsApi;
  onSelect: (id: string) => void;
}) {
  return (
    <div className="w-full max-w-[760px] mx-auto px-8 py-8 overflow-y-auto h-full">
      <div className="mb-6">
        <h1 className="text-[20px] font-semibold tracking-tight flex items-center gap-2">
          <Workflow size={18} strokeWidth={1.75} /> Automations
        </h1>
        <p className="text-[11px] text-[color:var(--muted-foreground)]">
          Describe a task in plain text — run it now, or set a schedule.
        </p>
      </div>

      {selected ? (
        <TaskDetail key={selected.id} task={selected} settings={settings} automations={automations} />
      ) : (
        <TaskComposer settings={settings} automations={automations} onCreated={onSelect} />
      )}
    </div>
  );
}

/* ─────────────────────────── Composer (new task → starts interview) ─────────────────────────── */

function TaskComposer({
  settings, automations, onCreated,
}: {
  settings: Settings;
  automations: AutomationsApi;
  onCreated: (id: string) => void;
}) {
  const [intent, setIntent] = useState('');
  const [modelKey, setModelKey] = useState(
    `${settings.defaultModel.provider}:${settings.defaultModel.model}`
  );
  const [busy, setBusy] = useState(false);
  const [provider, model] = splitModelKey(modelKey);
  const apiKey = findApiKey(settings, provider);
  const canSubmit = intent.trim().length > 0 && !!apiKey && !busy;
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const acRef = useRef<MentionAutocompleteHandle>(null);

  const start = async () => {
    const text = intent.trim();
    if (!text || !apiKey) return;
    setBusy(true);
    const id = await automations.createTask('', 'manual', provider, model);
    onCreated(id);
    // Fire-and-forget — chatBusy/chatError on the hook surface progress and errors
    // inside InterviewChat once it mounts. TaskComposer unmounts on onCreated().
    void automations.chat(id, text);
  };

  const pickStarter = (text: string) => {
    setIntent(text);
    requestAnimationFrame(() => textareaRef.current?.focus());
  };

  const insertMention = (name: string) => {
    const next = intent ? `${intent} @${name} ` : `@${name} `;
    setIntent(next);
    requestAnimationFrame(() => {
      const ta = textareaRef.current;
      if (!ta) return;
      ta.focus();
      ta.setSelectionRange(next.length, next.length);
    });
  };

  return (
    <div className="rounded-2xl border border-[color:var(--border)] bg-white p-4 space-y-3">
      <div className="relative">
        <MentionAutocomplete ref={acRef} textareaRef={textareaRef} value={intent} onChange={setIntent} />
        <textarea
          ref={textareaRef}
          value={intent}
          onChange={(e) => setIntent(e.target.value)}
          onKeyDown={(e) => { acRef.current?.handleKeyDown(e); }}
          placeholder="What do you want to automate? Type @ to use Gmail and other integrations."
          rows={4}
          className="w-full resize-none bg-transparent text-[14px] outline-none placeholder:text-[color:var(--muted-foreground)]"
        />
      </div>

      {intent === '' && (
        <div className="space-y-2 -mt-1">
          <div className="flex flex-wrap gap-1.5">
            {STARTER_PROMPTS.map((p) => (
              <button
                key={p}
                type="button"
                onClick={() => pickStarter(p)}
                className="h-7 px-3 rounded-full bg-[color:var(--surface-muted)] hover:bg-[color:var(--accent)] text-[12px] text-[color:var(--muted-foreground)] hover:text-[color:var(--foreground)] transition"
              >
                {p}
              </button>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-[11px] text-[color:var(--muted-foreground)]">Try with:</span>
            {TOOL_DESCRIPTORS.map((t) => {
              const connected = !!settings.tools?.[t.name]?.connected;
              return (
                <button
                  key={t.name}
                  type="button"
                  onClick={() => insertMention(t.name)}
                  className="inline-flex items-center gap-1 h-6 pl-1 pr-2 rounded-full border border-[color:var(--border)] bg-white hover:bg-[color:var(--surface-muted)] text-[11px] transition"
                >
                  {t.logoUrl && (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={t.logoUrl} alt="" className="w-3.5 h-3.5 object-contain" />
                  )}
                  <span>@{t.name}</span>
                  {!connected && (
                    <span className="text-[10px] text-[color:var(--muted-foreground)]">(connect)</span>
                  )}
                </button>
              );
            })}
          </div>
        </div>
      )}

      <div className="flex items-center justify-between gap-3 flex-wrap">
        <ModelSelect settings={settings} value={modelKey} onChange={setModelKey} />
        <button
          type="button"
          onClick={start}
          disabled={!canSubmit}
          className="inline-flex items-center gap-1.5 h-9 px-4 rounded-xl bg-[color:var(--primary)] text-white text-[13px] font-medium hover:opacity-90 transition disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {busy ? <Loader2 size={14} className="animate-spin" /> : <MessageSquare size={14} strokeWidth={2} />}
          Start interview
        </button>
      </div>
      {!apiKey && (
        <p className="text-[12px] text-[#D4183D]">
          No API key for {PROVIDER_NAMES[provider]}. Add one in Settings first.
        </p>
      )}
    </div>
  );
}

/* ─────────────────────────── Detail (selected task) ─────────────────────────── */

function TaskDetail({
  task, settings, automations,
}: {
  task: Task;
  settings: Settings;
  automations: AutomationsApi;
}) {
  return task.prompt.trim()
    ? <SkillReady task={task} settings={settings} automations={automations} />
    : <InterviewChat task={task} settings={settings} automations={automations} />;
}

/* ─────────────── Drafting mode: chat with the interviewer ─────────────── */

function InterviewChat({
  task, settings, automations,
}: {
  task: Task;
  settings: Settings;
  automations: AutomationsApi;
}) {
  const [draft, setDraft] = useState('');
  const scrollRef = useRef<HTMLDivElement>(null);
  const chatTextareaRef = useRef<HTMLTextAreaElement>(null);
  const acRef = useRef<MentionAutocompleteHandle>(null);
  const apiKey = findApiKey(settings, task.provider);
  const busy = !!automations.chatBusy[task.id];
  const error = automations.chatError[task.id];

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [task.messages.length, busy]);

  const send = (text: string) => {
    const t = text.trim();
    if (!t || !apiKey || busy) return;
    setDraft('');
    void automations.chat(task.id, t);
  };

  const lastIdx = task.messages.length - 1;
  const lastMsg = task.messages[lastIdx];
  const showTyping = busy && lastMsg?.role === 'user';

  return (
    <div className="rounded-2xl border border-[color:var(--border)] bg-white p-4 space-y-3">
      <div ref={scrollRef} className="space-y-3 max-h-[55vh] overflow-y-auto pr-1">
        {task.messages.length === 0 && !busy && (
          <p className="text-[13px] text-[color:var(--muted-foreground)]">Starting interview…</p>
        )}
        {task.messages.map((m, i) => (
          <MessageBubble
            key={i}
            m={m}
            options={i === lastIdx && m.role === 'assistant' && !busy ? m.options : undefined}
            onPick={send}
          />
        ))}
        {showTyping && (
          <div className="flex">
            <div className="inline-flex items-center gap-1.5 rounded-2xl bg-[color:var(--surface-muted)] px-3 py-2 text-[12px] text-[color:var(--muted-foreground)]">
              <Loader2 size={12} className="animate-spin" /> Thinking…
            </div>
          </div>
        )}
      </div>

      {error && (
        <p className="flex items-center gap-1.5 text-[12px] text-[#D4183D]">
          <AlertCircle size={14} strokeWidth={2} /> {error}
        </p>
      )}

      <div className="flex items-end gap-2 pt-2 border-t border-[color:var(--border)] relative">
        <div className="flex-1 relative">
          <MentionAutocomplete ref={acRef} textareaRef={chatTextareaRef} value={draft} onChange={setDraft} />
          <textarea
            ref={chatTextareaRef}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (acRef.current?.handleKeyDown(e)) return;
              if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void send(draft); }
            }}
            rows={2}
            disabled={busy || !apiKey}
            placeholder="Your answer… (or click an option above; type @ for integrations)"
            className="w-full resize-none bg-transparent text-[13px] outline-none placeholder:text-[color:var(--muted-foreground)] disabled:opacity-60"
          />
        </div>
        <button
          type="button"
          onClick={() => void send(draft)}
          disabled={!draft.trim() || busy || !apiKey}
          aria-label="Send"
          className="h-9 w-9 inline-flex items-center justify-center rounded-xl bg-[color:var(--primary)] text-white hover:opacity-90 transition disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <Send size={14} strokeWidth={2} />
        </button>
      </div>

      {!apiKey && (
        <p className="text-[12px] text-[#D4183D]">
          No API key for {PROVIDER_NAMES[task.provider]}. Add one in Settings first.
        </p>
      )}
    </div>
  );
}

function MessageBubble({
  m, options, onPick,
}: {
  m: InterviewMessage;
  options?: string[];
  onPick: (option: string) => void | Promise<void>;
}) {
  if (m.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="rounded-2xl bg-[color:var(--primary)] text-white px-3 py-2 text-[13px] max-w-[80%] whitespace-pre-wrap">
          {m.content}
        </div>
      </div>
    );
  }
  return (
    <div className="flex flex-col items-start gap-1.5 max-w-[85%]">
      <div className="rounded-2xl bg-[color:var(--surface-muted)] px-3 py-2 text-[13px] whitespace-pre-wrap">
        {m.content}
      </div>
      {options && options.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {options.map((opt) => (
            <button
              key={opt}
              type="button"
              onClick={() => void onPick(opt)}
              className="h-7 px-3 rounded-full border border-[color:var(--border)] bg-white text-[12px] hover:bg-[color:var(--surface-muted)] transition"
            >
              {opt}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/* ─────────────── Ready mode: skill compiled, runnable ─────────────── */

function SkillReady({
  task, settings, automations,
}: {
  task: Task;
  settings: Settings;
  automations: AutomationsApi;
}) {
  const apiKey = findApiKey(settings, task.provider);
  const running = task.status === 'running';

  return (
    <div className="rounded-2xl border border-[color:var(--border)] bg-white p-4 space-y-3">
      {task.messages.length > 0 && (
        <details className="rounded-lg border border-[color:var(--border)] bg-[color:var(--surface-muted)] px-3 py-2">
          <summary className="cursor-pointer text-[12px] font-medium text-[color:var(--muted-foreground)] inline-flex items-center gap-1.5">
            <MessageSquare size={12} strokeWidth={1.75} /> View interview ({task.messages.length} messages)
          </summary>
          <div className="mt-2 space-y-1.5">
            {task.messages.map((m, i) => (
              <div key={i} className={m.role === 'user' ? 'text-right' : 'text-left'}>
                <span
                  className={`inline-block rounded-lg px-2 py-1 text-[12px] whitespace-pre-wrap max-w-[85%] ${
                    m.role === 'user' ? 'bg-white border border-[color:var(--border)]' : 'bg-white/60'
                  }`}
                >
                  {m.content}
                </span>
              </div>
            ))}
          </div>
        </details>
      )}

      <textarea
        value={task.prompt}
        onChange={(e) => automations.updateTask(task.id, { prompt: e.target.value })}
        rows={5}
        disabled={running}
        className="w-full resize-none bg-transparent text-[14px] outline-none disabled:opacity-60"
      />
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <ModelSelect
            settings={settings}
            value={`${task.provider}:${task.model}`}
            onChange={(key) => {
              const [p, m] = splitModelKey(key);
              automations.updateTask(task.id, { provider: p, model: m });
            }}
          />
          <ScheduleSelect value={task.schedule} onChange={(s) => automations.updateTask(task.id, { schedule: s })} />
        </div>
        {running ? (
          <button
            type="button"
            onClick={() => automations.cancel(task.id)}
            className="inline-flex items-center gap-1.5 h-9 px-3 rounded-xl border border-[color:var(--border)] text-[13px] font-medium hover:bg-[color:var(--surface-muted)] transition"
          >
            <Square size={13} strokeWidth={2} /> Stop
          </button>
        ) : (
          <button
            type="button"
            onClick={() => apiKey && automations.runTask(task.id)}
            disabled={!apiKey || !task.prompt.trim()}
            className="inline-flex items-center gap-1.5 h-9 px-4 rounded-xl bg-[color:var(--primary)] text-white text-[13px] font-medium hover:opacity-90 transition disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <Play size={14} strokeWidth={2} /> Run
          </button>
        )}
      </div>

      {!apiKey && (
        <p className="text-[12px] text-[#D4183D]">
          No API key for {PROVIDER_NAMES[task.provider]}. Add one in Settings first.
        </p>
      )}
      {task.error && (
        <p className="flex items-center gap-1.5 text-[12px] text-[#D4183D]">
          <AlertCircle size={14} strokeWidth={2} /> {task.error}
        </p>
      )}

      {(task.transcript.length > 0 || task.output || running) && (
        <div className="pt-3 border-t border-[color:var(--border)] space-y-2">
          {(() => {
            const steps = task.transcript;
            const process = steps.length && steps[steps.length - 1].kind === 'assistant' ? steps.slice(0, -1) : steps;
            return process.map((s, i) =>
              s.kind === 'tool' ? (
                <ToolCard key={i} step={s} />
              ) : (
                <div key={i} className="text-[13px] text-[color:var(--muted-foreground)]">
                  <MarkdownRenderer content={s.text} />
                </div>
              )
            );
          })()}

          <div className="flex items-center gap-1.5 text-[11px] font-semibold tracking-[0.08em] uppercase text-[color:var(--muted-foreground)] pt-1">
            {running && <Loader2 size={12} className="animate-spin" />} Result
          </div>
          {task.output ? (
            <MarkdownRenderer content={task.output} />
          ) : (
            <p className="text-[13px] text-[color:var(--muted-foreground)]">Working…</p>
          )}
        </div>
      )}
    </div>
  );
}

const TOOL_ICONS: Record<string, typeof Wrench> = {
  web_search: Search,
  web_fetch: Globe,
  http: Send,
};

function ToolCard({ step }: { step: ToolStep }) {
  const Icon = TOOL_ICONS[step.tool] ?? Wrench;
  return (
    <details className="rounded-lg border border-[color:var(--border)] bg-[color:var(--surface-muted)] px-3 py-2">
      <summary className="flex items-center gap-2 cursor-pointer list-none text-[12px]">
        <Icon size={14} strokeWidth={1.75} className="shrink-0 text-[color:var(--muted-foreground)]" />
        <span className="font-medium truncate">{step.tool}</span>
        <span className="truncate text-[color:var(--muted-foreground)]">{step.args}</span>
        {step.ok ? (
          <Check size={12} strokeWidth={2.5} className="ml-auto shrink-0 text-[#10A37F]" />
        ) : (
          <AlertCircle size={12} strokeWidth={2} className="ml-auto shrink-0 text-[#D4183D]" />
        )}
      </summary>
      <pre className="mt-2 text-[11px] whitespace-pre-wrap break-words text-[color:var(--muted-foreground)] max-h-48 overflow-y-auto">
        {step.result || '…'}
      </pre>
    </details>
  );
}

/* ─────────────────────────── Shared selects ─────────────────────────── */

function splitModelKey(key: string): [Provider, string] {
  const idx = key.indexOf(':');
  return [key.slice(0, idx) as Provider, key.slice(idx + 1)];
}

function ModelSelect({
  settings, value, onChange,
}: {
  settings: Settings;
  value: string;
  onChange: (key: string) => void;
}) {
  const [selProvider, selModel] = splitModelKey(value);

  const modelsByProvider = useMemo(() => {
    const list: { provider: Provider; model: string }[] = [];
    const seen = new Set<string>();
    for (const p of settings.providers) {
      for (const m of PROVIDER_MODELS[p.provider] ?? []) {
        const k = `${p.provider}:${m}`;
        if (seen.has(k)) continue;
        seen.add(k);
        list.push({ provider: p.provider, model: m });
      }
    }
    if (!seen.has(`${selProvider}:${selModel}`)) {
      list.unshift({ provider: selProvider, model: selModel });
    }
    const groups = new Map<Provider, typeof list>();
    for (const m of list) {
      const arr = groups.get(m.provider) ?? [];
      arr.push(m);
      groups.set(m.provider, arr);
    }
    return Array.from(groups.entries());
  }, [settings.providers, selProvider, selModel]);

  return (
    <Select value={value} onValueChange={(v) => { if (v) onChange(v); }}>
      <SelectTrigger
        aria-label="Choose model"
        className="h-8 max-w-[200px] rounded-full border-transparent bg-[color:var(--surface-muted)] hover:bg-[color:var(--accent)] text-[12px] font-medium px-2.5 gap-1.5 transition-colors"
      >
        <span className="flex items-center gap-1.5 truncate">
          <ProviderLogo provider={selProvider} size={14} className={PROVIDER_ACCENT[selProvider]} />
          <span className="truncate">{selModel}</span>
        </span>
      </SelectTrigger>
      <SelectContent className="rounded-xl p-1 min-w-[220px] border-[color:var(--border)] shadow-lg">
        {modelsByProvider.map(([provider, models], i) => (
          <SelectGroup key={provider}>
            {i > 0 && <SelectSeparator className="my-1" />}
            <SelectLabel className="px-2 pt-1 pb-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-[color:var(--muted-foreground)]">
              {PROVIDER_NAMES[provider]}
            </SelectLabel>
            {models.map((m) => (
              <SelectItem
                key={`${m.provider}:${m.model}`}
                value={`${m.provider}:${m.model}`}
                className="rounded-lg px-2 py-1.5 text-[13px] focus:bg-[color:var(--surface-muted)]"
              >
                <span className="truncate">{m.model}</span>
              </SelectItem>
            ))}
          </SelectGroup>
        ))}
      </SelectContent>
    </Select>
  );
}

function ScheduleSelect({
  value, onChange,
}: {
  value: TaskSchedule;
  onChange: (s: TaskSchedule) => void;
}) {
  return (
    <Select value={value} onValueChange={(v) => { if (v) onChange(v as TaskSchedule); }}>
      <SelectTrigger
        aria-label="Choose schedule"
        className="h-8 rounded-full border-transparent bg-[color:var(--surface-muted)] hover:bg-[color:var(--accent)] text-[12px] font-medium px-2.5 gap-1.5 transition-colors"
      >
        <span className="flex items-center gap-1.5">
          <Clock size={13} strokeWidth={1.75} />
          {TASK_SCHEDULE_LABELS[value]}
        </span>
      </SelectTrigger>
      <SelectContent className="rounded-xl p-1 min-w-[160px] border-[color:var(--border)] shadow-lg">
        {SCHEDULES.map((s) => (
          <SelectItem
            key={s}
            value={s}
            className="rounded-lg px-2 py-1.5 text-[13px] focus:bg-[color:var(--surface-muted)]"
          >
            {TASK_SCHEDULE_LABELS[s]}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
