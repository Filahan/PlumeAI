'use client';

import { useState, useEffect, useRef, useMemo, useCallback, ClipboardEvent, DragEvent, KeyboardEvent } from 'react';
import { Conversation, Message, Settings, Provider, AttachmentRef, findApiKey, supportsVision, PROVIDER_MODELS, PROVIDER_NAMES, PROVIDER_ACCENT } from '@/lib/types';
import { streamChat, generateTitle, ChatMessage, ImagePart } from '@/lib/api';
import { MarkdownRenderer } from '@/components/markdown-renderer';
import MentionAutocomplete, { type MentionAutocompleteHandle } from '@/components/mention-autocomplete';
import { Paperclip, ArrowUp, Copy, Check, X, ImagePlus, Wrench, AlertCircle } from 'lucide-react';
import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectSeparator, SelectTrigger } from '@/components/ui/select';
import { ProviderLogo } from '@/components/provider-logo';
import ImageThumb from '@/components/image-thumb';
import ImageLightbox from '@/components/image-lightbox';
import { putBlob, getBlob } from '@/lib/blob-store';
import { processImage, blobToBase64, MAX_IMAGES_PER_MESSAGE } from '@/lib/image';

interface PendingAttachment {
  localId: string;
  previewUrl: string;
  processing: boolean;
  ref?: AttachmentRef;
  error?: string;
}

async function messageToChatParts(text: string, attachments?: AttachmentRef[]): Promise<string | (ImagePart | { type: 'text'; text: string })[]> {
  if (!attachments || attachments.length === 0) return text;
  const parts: (ImagePart | { type: 'text'; text: string })[] = [];
  if (text) parts.push({ type: 'text', text });
  for (const a of attachments) {
    const blob = await getBlob(a.id);
    if (!blob) continue;
    const base64 = await blobToBase64(blob);
    parts.push({ type: 'image', mime: a.mime, base64 });
  }
  if (parts.length === 0 && text) parts.push({ type: 'text', text });
  return parts;
}

interface ChatViewProps {
  conversation: Conversation | null;
  settings: Settings;
  onAddMessage: (convId: string, msg: Omit<Message, 'id' | 'timestamp'>) => string;
  onUpdateMessage: (convId: string, msgId: string, content: string, replace?: boolean) => void;
  onCreateConversation: (provider: Provider, model: string) => string;
  onRenameConversation: (id: string, title: string) => void;
  onSetConversationModel: (id: string, provider: Provider, model: string) => void;
  onRecordUsage: (entry: { conversationId: string; provider: Provider; model: string; inputTokens: number; outputTokens: number }) => void;
  ready: boolean;
}

export default function ChatView({
  conversation, settings, onAddMessage, onUpdateMessage, onCreateConversation, onRenameConversation, onSetConversationModel, onRecordUsage, ready,
}: ChatViewProps) {
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [titleDraft, setTitleDraft] = useState<string | null>(null);
  const [draftProvider, setDraftProvider] = useState<Provider>(settings.defaultModel.provider);
  const [draftModel, setDraftModel] = useState<string>(settings.defaultModel.model);
  const [pendingAttachments, setPendingAttachments] = useState<PendingAttachment[]>([]);
  const [dragActive, setDragActive] = useState(false);
  const [lightboxRef, setLightboxRef] = useState<AttachmentRef | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!conversation) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setDraftProvider(settings.defaultModel.provider);
      setDraftModel(settings.defaultModel.model);
    }
  }, [conversation, settings.defaultModel.provider, settings.defaultModel.model]);

  const activeProvider = conversation?.provider ?? draftProvider;
  const activeModel = conversation?.model ?? draftModel;
  const visionOk = supportsVision(activeProvider, activeModel);
  const pendingProcessing = pendingAttachments.some((p) => p.processing);
  const readyAttachments = pendingAttachments.filter((p) => p.ref).map((p) => p.ref!);

  const addFiles = useCallback(async (files: File[]) => {
    if (files.length === 0) return;
    const room = MAX_IMAGES_PER_MESSAGE - pendingAttachments.length;
    if (room <= 0) {
      alert(`You can attach at most ${MAX_IMAGES_PER_MESSAGE} images per message.`);
      return;
    }
    const accepted = files.filter((f) => f.type.startsWith('image/')).slice(0, room);
    for (const file of accepted) {
      const localId = crypto.randomUUID();
      const previewUrl = URL.createObjectURL(file);
      setPendingAttachments((prev) => [...prev, { localId, previewUrl, processing: true }]);
      try {
        const processed = await processImage(file);
        const id = await putBlob(processed.blob);
        const ref: AttachmentRef = {
          id,
          mime: processed.mime,
          width: processed.width,
          height: processed.height,
          size: processed.size,
        };
        setPendingAttachments((prev) =>
          prev.map((p) => (p.localId === localId ? { ...p, processing: false, ref } : p))
        );
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Failed to process image';
        setPendingAttachments((prev) =>
          prev.map((p) => (p.localId === localId ? { ...p, processing: false, error: message } : p))
        );
      }
    }
  }, [pendingAttachments.length]);

  const removePending = useCallback((localId: string) => {
    setPendingAttachments((prev) => {
      const target = prev.find((p) => p.localId === localId);
      if (target) URL.revokeObjectURL(target.previewUrl);
      return prev.filter((p) => p.localId !== localId);
    });
  }, []);

  useEffect(() => {
    // Revoke object URLs on unmount.
    return () => {
      pendingAttachments.forEach((p) => URL.revokeObjectURL(p.previewUrl));
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handlePaste = useCallback((e: ClipboardEvent<HTMLTextAreaElement>) => {
    const items = Array.from(e.clipboardData?.items ?? []);
    const files: File[] = [];
    for (const item of items) {
      if (item.kind === 'file') {
        const file = item.getAsFile();
        if (file && file.type.startsWith('image/')) files.push(file);
      }
    }
    if (files.length > 0) {
      e.preventDefault();
      addFiles(files);
    }
  }, [addFiles]);

  const handleDrop = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragActive(false);
    const files = Array.from(e.dataTransfer?.files ?? []);
    if (files.length > 0) addFiles(files);
  }, [addFiles]);

  const handleDragOver = useCallback((e: DragEvent<HTMLDivElement>) => {
    if (e.dataTransfer?.types?.includes('Files')) {
      e.preventDefault();
      setDragActive(true);
    }
  }, []);

  const handleDragLeave = useCallback((e: DragEvent<HTMLDivElement>) => {
    // Only deactivate when leaving the outer container itself.
    if (e.target === e.currentTarget) setDragActive(false);
  }, []);

  const availableModels = useMemo(() => {
    const list: { provider: Provider; model: string; label: string }[] = [];
    const seen = new Set<string>();
    // Models from configured providers
    for (const p of settings.providers) {
      for (const m of PROVIDER_MODELS[p.provider] ?? []) {
        const key = `${p.provider}:${m}`;
        if (seen.has(key)) continue;
        seen.add(key);
        list.push({ provider: p.provider, model: m, label: `${PROVIDER_NAMES[p.provider]} · ${m}` });
      }
    }
    // Always include the currently-active one even if its provider isn't configured (so the UI doesn't go blank)
    const activeKey = `${activeProvider}:${activeModel}`;
    if (!seen.has(activeKey)) {
      list.unshift({ provider: activeProvider, model: activeModel, label: `${PROVIDER_NAMES[activeProvider]} · ${activeModel}` });
    }
    return list;
  }, [settings.providers, activeProvider, activeModel]);

  const modelsByProvider = useMemo(() => {
    const groups = new Map<Provider, typeof availableModels>();
    for (const m of availableModels) {
      const arr = groups.get(m.provider) ?? [];
      arr.push(m);
      groups.set(m.provider, arr);
    }
    return Array.from(groups.entries());
  }, [availableModels]);

  const handleModelChange = (value: string | null) => {
    if (!value) return;
    const [provider, ...rest] = value.split(':');
    const model = rest.join(':');
    if (conversation) {
      onSetConversationModel(conversation.id, provider as Provider, model);
    } else {
      setDraftProvider(provider as Provider);
      setDraftModel(model);
    }
  };
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const stickToBottomRef = useRef(true);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const controllerRef = useRef<AbortController | null>(null);
  const acRef = useRef<MentionAutocompleteHandle>(null);

  // In-flight tool calls for the assistant message currently being streamed. Cleared at the end
  // of each send. Not persisted — v1 chat keeps tool execution transient.
  interface InFlightToolCall { id: string; tool: string; args: string; ok?: boolean; result?: string }
  const [currentAssistantId, setCurrentAssistantId] = useState<string | null>(null);
  const [activeToolCalls, setActiveToolCalls] = useState<InFlightToolCall[]>([]);

  const lastMessage = conversation?.messages[conversation.messages.length - 1];

  const handleScroll = () => {
    const el = scrollContainerRef.current;
    if (!el) return;
    stickToBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  };

  // New message → snap instantly to bottom (the user just submitted; this is their action).
  useEffect(() => {
    const el = scrollContainerRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
    stickToBottomRef.current = true;
  }, [conversation?.messages.length]);

  // Streaming chunks → only follow the bottom if the user is still there.
  useEffect(() => {
    if (!stickToBottomRef.current) return;
    const el = scrollContainerRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [lastMessage?.content]);

  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = 'auto';
    ta.style.height = `${Math.min(ta.scrollHeight, 200)}px`;
  }, [input]);

  const handleSubmit = async () => {
    if ((!input.trim() && readyAttachments.length === 0) || isLoading || pendingProcessing) return;
    if (readyAttachments.length > 0 && !visionOk) {
      alert(`${activeModel} doesn't support images. Switch to a vision-capable model (e.g., gpt-4o, claude-3-5-sonnet).`);
      return;
    }
    const apiKey = findApiKey(settings, activeProvider);
    if (!apiKey) {
      alert(`No API key configured for ${PROVIDER_NAMES[activeProvider]}. Add one in Settings.`);
      return;
    }

    let convId = conversation?.id;
    if (!convId) convId = onCreateConversation(activeProvider, activeModel);

    const userContent = input.trim();
    const messageAttachments = readyAttachments;
    setInput('');
    pendingAttachments.forEach((p) => URL.revokeObjectURL(p.previewUrl));
    setPendingAttachments([]);

    const isFirstExchange = (conversation?.messages.length ?? 0) === 0;

    onAddMessage(convId, {
      role: 'user',
      content: userContent,
      ...(messageAttachments.length > 0 ? { attachments: messageAttachments } : {}),
    });
    const assistantMsgId = onAddMessage(convId, { role: 'assistant', content: '' });

    // Decide which streaming path to use. The tool-aware server route only supports text
    // (no image parts yet) and only non-Anthropic providers.
    const priorMessages = conversation?.messages ?? [];
    const historyHasImages = priorMessages.some((m) => m.attachments && m.attachments.length > 0);
    const newHasImages = messageAttachments.length > 0;
    const useToolPath = activeProvider !== 'anthropic' && !newHasImages && !historyHasImages;

    let assistantText = '';
    setIsLoading(true);
    setCurrentAssistantId(assistantMsgId);
    setActiveToolCalls([]);

    if (useToolPath) {
      const controller = new AbortController();
      controllerRef.current = controller;
      try {
        const res = await fetch('/api/chat/stream', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            provider: activeProvider,
            model: activeModel,
            history: priorMessages.map((m) => ({ role: m.role, content: m.content })),
            newMessage: userContent,
          }),
          signal: controller.signal,
        });
        if (!res.ok || !res.body) throw new Error(`Chat stream failed (${res.status})`);

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';
          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            let evt: { type: string; [k: string]: unknown };
            try { evt = JSON.parse(line.slice(6)); } catch { continue; }
            if (evt.type === 'text' && typeof evt.delta === 'string') {
              assistantText += evt.delta;
              onUpdateMessage(convId, assistantMsgId, evt.delta);
            } else if (evt.type === 'tool_call') {
              setActiveToolCalls((prev) => [...prev, { id: String(evt.id), tool: String(evt.tool), args: String(evt.args ?? '') }]);
            } else if (evt.type === 'tool_result') {
              setActiveToolCalls((prev) =>
                prev.map((c) => (c.id === String(evt.id) ? { ...c, ok: !!evt.ok, result: String(evt.result ?? '') } : c))
              );
            } else if (evt.type === 'error' && typeof evt.message === 'string') {
              onUpdateMessage(convId, assistantMsgId, '\n\nError: ' + evt.message);
            }
          }
        }
      } catch (err) {
        if (!controller.signal.aborted) {
          const message = err instanceof Error ? err.message : 'Unknown error';
          onUpdateMessage(convId, assistantMsgId, 'Error: ' + message);
          setIsLoading(false);
          setCurrentAssistantId(null);
          controllerRef.current = null;
          return;
        }
      } finally {
        setIsLoading(false);
        setCurrentAssistantId(null);
        setActiveToolCalls([]);
        controllerRef.current = null;
      }
    } else {
      // Legacy path: direct client → provider streaming (supports images + Anthropic).
      const history: ChatMessage[] = [];
      for (const m of priorMessages) {
        const parts = await messageToChatParts(m.content, m.attachments);
        history.push({ role: m.role, content: parts });
      }
      history.push({
        role: 'user',
        content: await messageToChatParts(userContent, messageAttachments),
      });

      try {
        const { controller, done } = await streamChat(
          activeProvider, activeModel, apiKey, history,
          (chunk) => {
            assistantText += chunk;
            onUpdateMessage(convId!, assistantMsgId, chunk);
          },
          (usage) => onRecordUsage({ conversationId: convId!, provider: activeProvider, model: activeModel, ...usage })
        );
        controllerRef.current = controller;
        await done;
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Unknown error';
        onUpdateMessage(convId, assistantMsgId, 'Error: ' + message);
        setIsLoading(false);
        setCurrentAssistantId(null);
        controllerRef.current = null;
        return;
      } finally {
        setIsLoading(false);
        setCurrentAssistantId(null);
        controllerRef.current = null;
      }
    }

    if (isFirstExchange && assistantText) {
      generateTitle(activeProvider, activeModel, apiKey, userContent, assistantText)
        .then((title) => {
          if (title) onRenameConversation(convId!, title);
        })
        .catch(() => {
          // title generation is best-effort — fall back to the default title silently
        });
    }
  };

  const handleStop = () => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    setIsLoading(false);
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSubmit(); }
  };

  const handleCopy = async (id: string, content: string) => {
    try {
      await navigator.clipboard.writeText(content);
      setCopiedId(id);
      setTimeout(() => setCopiedId((curr) => (curr === id ? null : curr)), 1500);
    } catch {
      // clipboard access denied — silently ignore
    }
  };

  const hasMessages = conversation && conversation.messages.length > 0;

  const sendDisabled = isLoading || pendingProcessing || (!input.trim() && readyAttachments.length === 0);

  const InputBox = (
    <div className="bg-white rounded-2xl border border-[color:var(--border)] px-4 pt-3 pb-3 focus-within:border-[color:var(--ring)] transition-colors">
      {pendingAttachments.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-3">
          {pendingAttachments.map((p) => (
            <div key={p.localId} className="relative w-16 h-16 rounded-xl overflow-hidden bg-[color:var(--surface-muted)] border border-[color:var(--border)]">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={p.previewUrl} alt="" className="w-full h-full object-cover" />
              {p.processing && (
                <div className="absolute inset-0 bg-white/60 flex items-center justify-center">
                  <div className="w-4 h-4 rounded-full border-2 border-black/30 border-t-black/80 animate-spin" />
                </div>
              )}
              {p.error && (
                <div className="absolute inset-0 bg-red-500/20 flex items-center justify-center text-[10px] text-red-700 px-1 text-center font-medium" title={p.error}>
                  error
                </div>
              )}
              <button
                type="button"
                onClick={() => removePending(p.localId)}
                aria-label="Remove image"
                className="absolute top-0.5 right-0.5 w-5 h-5 rounded-full bg-black/80 text-white flex items-center justify-center hover:bg-black"
              >
                <X size={11} strokeWidth={2.5} />
              </button>
            </div>
          ))}
        </div>
      )}

      <div className="relative">
        <MentionAutocomplete ref={acRef} textareaRef={textareaRef} value={input} onChange={setInput} />
        <textarea
          ref={textareaRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (acRef.current?.handleKeyDown(e)) return;
            handleKeyDown(e);
          }}
          onPaste={handlePaste}
          placeholder="Message PlumeAI… (type @ for tools)"
          rows={1}
          className="w-full resize-none bg-transparent text-[14px] text-[color:var(--foreground)] placeholder:text-[color:var(--muted-foreground)] outline-none min-h-[24px] max-h-[200px] leading-relaxed"
          disabled={isLoading}
        />
      </div>

      <div className="flex items-center justify-between mt-2 gap-2">
        <div className="flex items-center gap-1.5 min-w-0">
          <Select value={`${activeProvider}:${activeModel}`} onValueChange={handleModelChange}>
            <SelectTrigger
              aria-label="Choose model"
              className="h-8 max-w-[240px] rounded-full border-transparent bg-transparent hover:bg-[color:var(--surface-muted)] text-[12px] font-medium text-[color:var(--foreground)] px-2.5 gap-1.5 transition-colors"
            >
              <span className="flex items-center gap-1.5 truncate">
                <ProviderLogo provider={activeProvider} size={14} className={PROVIDER_ACCENT[activeProvider]} />
                <span className="truncate">
                  {availableModels.find((m) => `${m.provider}:${m.model}` === `${activeProvider}:${activeModel}`)?.label ?? activeModel}
                </span>
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

          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            multiple
            className="hidden"
            onChange={(e) => {
              const files = Array.from(e.target.files ?? []);
              addFiles(files);
              if (fileInputRef.current) fileInputRef.current.value = '';
            }}
          />
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            aria-label="Attach image"
            className="w-8 h-8 shrink-0 rounded-full flex items-center justify-center text-[color:var(--muted-foreground)] hover:bg-[color:var(--surface-muted)] hover:text-[color:var(--foreground)] transition-colors"
          >
            <Paperclip size={16} strokeWidth={1.75} />
          </button>
        </div>

        {isLoading ? (
          <button
            type="button"
            onClick={handleStop}
            aria-label="Stop generating"
            className="inline-flex items-center gap-1.5 h-9 px-4 rounded-full bg-[color:var(--primary)] text-white text-[13px] font-medium hover:opacity-90 transition"
          >
            <span className="w-2.5 h-2.5 bg-white rounded-[2px]" />
            Stop
          </button>
        ) : (
          <button
            type="button"
            onClick={handleSubmit}
            disabled={sendDisabled}
            aria-label="Send message"
            className="inline-flex items-center gap-1.5 h-9 px-4 rounded-full bg-[color:var(--primary)] text-white text-[13px] font-medium hover:opacity-90 transition disabled:opacity-30 disabled:cursor-not-allowed"
          >
            Send
            <ArrowUp size={14} strokeWidth={2.5} />
          </button>
        )}
      </div>
    </div>
  );

  return (
    <div
      className="flex flex-col h-full relative"
      onDragEnter={handleDragOver}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      <ImageLightbox attachment={lightboxRef} onClose={() => setLightboxRef(null)} />
      {dragActive && (
        <div className="fixed inset-0 z-[55] bg-emerald-500/10 border-4 border-dashed border-emerald-500 flex items-center justify-center pointer-events-none">
          <div className="rounded-2xl bg-white px-6 py-4 shadow-xl flex items-center gap-3 text-[color:var(--foreground)]">
            <ImagePlus size={20} strokeWidth={2} className="text-emerald-600" />
            <span className="text-[13px] font-medium">Drop images to attach</span>
          </div>
        </div>
      )}

      {hasMessages && (
        <header className="shrink-0 h-14 flex items-center pl-6 pr-32 border-b border-[color:var(--border)]">
          <input
            value={titleDraft ?? conversation!.title}
            onChange={(e) => setTitleDraft(e.target.value)}
            onFocus={() => setTitleDraft(conversation!.title)}
            onBlur={() => {
              const t = titleDraft?.trim();
              if (t && t !== conversation!.title) onRenameConversation(conversation!.id, t);
              setTitleDraft(null);
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') { e.preventDefault(); (e.target as HTMLInputElement).blur(); }
              if (e.key === 'Escape') { setTitleDraft(null); (e.target as HTMLInputElement).blur(); }
            }}
            className="text-[15px] font-medium bg-transparent outline-none focus:bg-[color:var(--surface-muted)] rounded px-2 py-0.5 -ml-2 max-w-full"
            aria-label="Conversation title"
          />
        </header>
      )}

      {!ready ? (
        <div className="flex-1" />
      ) : hasMessages ? (
        <>
          <div ref={scrollContainerRef} onScroll={handleScroll} className="flex-1 overflow-y-auto">
            <div className="max-w-[768px] mx-auto px-6 py-6 space-y-5">
              {conversation!.messages.map((msg) => (
                msg.role === 'user' ? (
                  <div key={msg.id} className="group flex flex-col items-end gap-1">
                    {msg.attachments && msg.attachments.length > 0 && (
                      <div className="flex flex-wrap gap-2 justify-end max-w-[80%]">
                        {msg.attachments.map((a) => (
                          <ImageThumb key={a.id} attachment={a} size={88} onClick={() => setLightboxRef(a)} />
                        ))}
                      </div>
                    )}
                    {msg.content && (
                      <div className="max-w-[80%] bg-[color:var(--surface-muted)] rounded-2xl px-4 py-2.5 text-[14px] leading-relaxed text-[color:var(--foreground)] whitespace-pre-wrap break-words">
                        {msg.content}
                      </div>
                    )}
                    <button
                      type="button"
                      onClick={() => handleCopy(msg.id, msg.content)}
                      aria-label="Copy message"
                      className="h-7 w-7 inline-flex items-center justify-center rounded-md text-[color:var(--muted-foreground)] hover:bg-[color:var(--surface-muted)] opacity-0 group-hover:opacity-100 focus-visible:opacity-100 transition"
                    >
                      {copiedId === msg.id ? <Check size={14} /> : <Copy size={14} />}
                    </button>
                  </div>
                ) : msg.content || msg.id === currentAssistantId ? (
                  <div key={msg.id} className="group max-w-[90%] w-fit">
                    {msg.id === currentAssistantId && activeToolCalls.length > 0 && (
                      <div className="mb-2 space-y-1.5">
                        {activeToolCalls.map((tc) => (
                          <details key={tc.id} className="rounded-lg border border-[color:var(--border)] bg-[color:var(--surface-muted)] px-3 py-1.5 max-w-[400px]">
                            <summary className="flex items-center gap-2 cursor-pointer list-none text-[12px]">
                              <Wrench size={12} strokeWidth={1.75} className="shrink-0 text-[color:var(--muted-foreground)]" />
                              <span className="font-medium truncate">{tc.tool}</span>
                              <span className="truncate text-[color:var(--muted-foreground)]">{tc.args}</span>
                              {tc.result === undefined ? (
                                <span className="ml-auto w-2 h-2 rounded-full bg-[#6366f1] animate-pulse shrink-0" aria-label="Running" />
                              ) : tc.ok ? (
                                <Check size={12} strokeWidth={2.5} className="ml-auto shrink-0 text-[#10A37F]" />
                              ) : (
                                <AlertCircle size={12} strokeWidth={2} className="ml-auto shrink-0 text-[#D4183D]" />
                              )}
                            </summary>
                            {tc.result !== undefined && (
                              <pre className="mt-1.5 text-[11px] whitespace-pre-wrap break-words text-[color:var(--muted-foreground)] max-h-32 overflow-y-auto">
                                {tc.result || '…'}
                              </pre>
                            )}
                          </details>
                        ))}
                      </div>
                    )}
                    {msg.content && (
                      <div className="rounded-2xl px-4 py-3 text-[14px] leading-relaxed text-[color:var(--foreground)]">
                        <MarkdownRenderer content={msg.content} />
                      </div>
                    )}
                    {msg.content && (
                      <button
                        type="button"
                        onClick={() => handleCopy(msg.id, msg.content)}
                        aria-label="Copy response"
                        className="mt-1 h-7 w-7 inline-flex items-center justify-center rounded-md text-[color:var(--muted-foreground)] hover:bg-[color:var(--surface-muted)] opacity-0 group-hover:opacity-100 focus-visible:opacity-100 transition"
                      >
                        {copiedId === msg.id ? <Check size={14} /> : <Copy size={14} />}
                      </button>
                    )}
                  </div>
                ) : null
              ))}
            </div>
          </div>

          <div className="shrink-0 px-6 pb-4 pt-2 bg-white">
            <div className="max-w-[768px] mx-auto">{InputBox}</div>
          </div>
        </>
      ) : (
        <div className="flex-1 flex flex-col items-center justify-center px-6 pb-6">
          <div className="w-full max-w-[640px]">
            <div className="flex justify-center mb-4">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src="/logo.png" alt="" className="h-15 w-auto" />
            </div>
            <h1 className="text-[28px] font-medium mb-6 tracking-tight text-center">
              What can I help you with?
            </h1>
            {InputBox}
          </div>
        </div>
      )}
    </div>
  );
}
