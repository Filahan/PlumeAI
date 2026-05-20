'use client';

import { useState, useEffect, useRef, useMemo, useCallback, ClipboardEvent, DragEvent, KeyboardEvent } from 'react';
import { Conversation, Message, Settings, Provider, AttachmentRef, findApiKey, supportsVision, PROVIDER_MODELS, PROVIDER_NAMES } from '@/lib/types';
import { streamChat, generateTitle, ChatMessage, ImagePart } from '@/lib/api';
import { MarkdownRenderer } from '@/components/markdown-renderer';
import { Paperclip, ArrowUp, Copy, Check, RotateCcw, ArrowRight, X, Eye, ImagePlus } from 'lucide-react';
import { Select, SelectContent, SelectItem, SelectTrigger } from '@/components/ui/select';
import SettingsContent from '@/components/settings-content';
import { ProviderLogo, PROVIDER_ACCENT } from '@/components/provider-logo';
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
  setSettings: (s: Settings) => void;
  onAddMessage: (convId: string, msg: Omit<Message, 'id' | 'timestamp'>) => string;
  onUpdateMessage: (convId: string, msgId: string, content: string, replace?: boolean) => void;
  onCreateConversation: (provider: Provider, model: string) => string;
  onRenameConversation: (id: string, title: string) => void;
  onSetConversationModel: (id: string, provider: Provider, model: string) => void;
  onRecordUsage: (entry: { conversationId: string; provider: Provider; model: string; inputTokens: number; outputTokens: number }) => void;
  ready: boolean;
}

export default function ChatView({
  conversation, settings, setSettings, onAddMessage, onUpdateMessage, onCreateConversation, onRenameConversation, onSetConversationModel, onRecordUsage, ready,
}: ChatViewProps) {
  const [hasStarted, setHasStarted] = useState(settings.providers.length > 0);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [copiedId, setCopiedId] = useState<string | null>(null);
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
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const controllerRef = useRef<AbortController | null>(null);

  const lastMessage = conversation?.messages[conversation.messages.length - 1];

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [conversation?.messages.length, lastMessage?.content]);

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

    // Build history. Existing messages may have attachments — resolve their blobs to image parts.
    const priorMessages = conversation?.messages ?? [];
    const history: ChatMessage[] = [];
    for (const m of priorMessages) {
      const parts = await messageToChatParts(m.content, m.attachments);
      history.push({ role: m.role, content: parts });
    }
    history.push({
      role: 'user',
      content: await messageToChatParts(userContent, messageAttachments),
    });

    let assistantText = '';
    setIsLoading(true);
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
      return;
    } finally {
      setIsLoading(false);
      controllerRef.current = null;
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

  const handleRegenerate = async (assistantMsgId: string) => {
    if (!conversation || isLoading) return;
    const apiKey = findApiKey(settings, conversation.provider);
    if (!apiKey) {
      alert(`No API key configured for ${PROVIDER_NAMES[conversation.provider]}. Add one in Settings.`);
      return;
    }
    const idx = conversation.messages.findIndex((m) => m.id === assistantMsgId);
    if (idx <= 0) return;
    const priorMessages = conversation.messages.slice(0, idx);
    const history: ChatMessage[] = [];
    for (const m of priorMessages) {
      const parts = await messageToChatParts(m.content, m.attachments);
      history.push({ role: m.role, content: parts });
    }
    onUpdateMessage(conversation.id, assistantMsgId, '', true);
    setIsLoading(true);
    try {
      const { controller, done } = await streamChat(
        conversation.provider, conversation.model, apiKey, history,
        (chunk) => onUpdateMessage(conversation.id, assistantMsgId, chunk),
        (usage) => onRecordUsage({ conversationId: conversation.id, provider: conversation.provider, model: conversation.model, ...usage })
      );
      controllerRef.current = controller;
      await done;
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error';
      onUpdateMessage(conversation.id, assistantMsgId, 'Error: ' + message);
    } finally {
      setIsLoading(false);
      controllerRef.current = null;
    }
  };

  const hasMessages = conversation && conversation.messages.length > 0;

  const sendDisabled = isLoading || pendingProcessing || (!input.trim() && readyAttachments.length === 0);

  const InputBox = (
    <div className="bg-[#F4F4F4] rounded-[28px] px-5 pt-4 pb-3.5 transition-shadow focus-within:shadow-[0_0_0_2px_rgba(0,0,0,0.06)]">
      {pendingAttachments.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-3">
          {pendingAttachments.map((p) => (
            <div key={p.localId} className="relative w-16 h-16 rounded-xl overflow-hidden bg-white border border-black/[0.06]">
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

      <textarea
        ref={textareaRef}
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKeyDown}
        onPaste={handlePaste}
        placeholder="Ask anything"
        rows={1}
        className="w-full resize-none bg-transparent text-[17px] text-[#1c1c1c] placeholder:text-[#b4b4b4] outline-none min-h-[28px] max-h-[200px] leading-relaxed"
        disabled={isLoading}
      />

      <div className="flex items-center justify-between mt-2.5 gap-2">
        <div className="flex items-center gap-1 min-w-0">
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
            className="w-8 h-8 shrink-0 rounded-full flex items-center justify-center text-[#8e8e8e] hover:bg-[#e8e8e8] hover:text-[#5a5a5a] transition-colors"
          >
            <Paperclip size={16} strokeWidth={1.5} />
          </button>

          <Select value={`${activeProvider}:${activeModel}`} onValueChange={handleModelChange}>
            <SelectTrigger
              aria-label="Choose model"
              className="h-8 max-w-[260px] rounded-full border-transparent bg-transparent hover:bg-[#e8e8e8] text-[13px] font-medium text-[#5a5a5a] px-2.5 gap-1 transition-colors"
            >
              <span className="flex items-center gap-1.5 truncate">
                <span className="truncate">
                  {availableModels.find((m) => `${m.provider}:${m.model}` === `${activeProvider}:${activeModel}`)?.label ?? activeModel}
                </span>
                {visionOk && <Eye size={12} strokeWidth={2} className="text-emerald-600/80 shrink-0" />}
              </span>
            </SelectTrigger>
            <SelectContent className="rounded-xl">
              {availableModels.map((m) => (
                <SelectItem key={`${m.provider}:${m.model}`} value={`${m.provider}:${m.model}`}>
                  {m.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="shrink-0">
          {isLoading ? (
            <button
              type="button"
              onClick={handleStop}
              aria-label="Stop generating"
              className="w-9 h-9 rounded-full bg-black text-white flex items-center justify-center hover:bg-[#333] transition-colors"
            >
              <div className="w-3 h-3 bg-white rounded-[2px]" />
            </button>
          ) : (
            <button
              type="button"
              onClick={handleSubmit}
              disabled={sendDisabled}
              aria-label="Send message"
              className="w-9 h-9 rounded-full bg-black text-white flex items-center justify-center hover:bg-[#333] transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
            >
              <ArrowUp size={16} strokeWidth={2.5} />
            </button>
          )}
        </div>
      </div>
    </div>
  );

  return (
    <div
      className="flex flex-col min-h-screen relative"
      onDragEnter={handleDragOver}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      <ImageLightbox attachment={lightboxRef} onClose={() => setLightboxRef(null)} />
      {dragActive && (
        <div className="fixed inset-0 z-[55] bg-emerald-500/10 border-4 border-dashed border-emerald-500 flex items-center justify-center pointer-events-none">
          <div className="rounded-2xl bg-white px-6 py-4 shadow-xl flex items-center gap-3 text-[#1c1c1c]">
            <ImagePlus size={20} strokeWidth={2} className="text-emerald-600" />
            <span className="text-[15px] font-medium">Drop images to attach</span>
          </div>
        </div>
      )}
      {!ready ? (
        <div className="flex-1" />
      ) : hasMessages ? (
        <>
          {/* Messages — page scrolls naturally */}
          <div className="flex-1 w-full">
            <div className="max-w-[768px] mx-auto px-4 py-6 space-y-6">
              {conversation!.messages.map((msg, i) => {
                const isLastAssistant =
                  msg.role === 'assistant' && i === conversation!.messages.length - 1;
                const canRegenerate = msg.role === 'assistant' && !!msg.content && !(isLastAssistant && isLoading);
                return msg.role === 'user' ? (
                  <div key={msg.id} className="group flex flex-col items-end gap-1">
                    {msg.attachments && msg.attachments.length > 0 && (
                      <div className="flex flex-wrap gap-2 justify-end max-w-[80%]">
                        {msg.attachments.map((a) => (
                          <ImageThumb key={a.id} attachment={a} size={88} onClick={() => setLightboxRef(a)} />
                        ))}
                      </div>
                    )}
                    {msg.content && (
                      <div className="max-w-[80%] bg-[#F0EAEA] rounded-[20px] px-4 py-2.5 text-[18px] leading-relaxed text-[#1c1c1c] whitespace-pre-wrap break-words">
                        {msg.content}
                      </div>
                    )}
                    <button
                      type="button"
                      onClick={() => handleCopy(msg.id, msg.content)}
                      aria-label="Copy message"
                      className="h-7 w-7 inline-flex items-center justify-center rounded-md text-[#9b9b9b] hover:bg-[#EEEEEE] hover:text-[#5a5a5a] opacity-0 group-hover:opacity-100 focus-visible:opacity-100 transition"
                    >
                      {copiedId === msg.id ? <Check size={14} /> : <Copy size={14} />}
                    </button>
                  </div>
                ) : (
                  <div key={msg.id} className="group">
                    <div className="text-[18px] leading-relaxed text-[#1c1c1c] pr-8">
                      {msg.content ? (
                        <MarkdownRenderer content={msg.content} />
                      ) : (
                        <span
                          role="status"
                          aria-label="Generating response"
                          className="inline-block w-1.5 h-4 bg-[#b4b4b4] animate-pulse rounded-sm"
                        />
                      )}
                    </div>
                    {msg.content && (
                      <div className="mt-1.5 flex items-center gap-1 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition">
                        <button
                          type="button"
                          onClick={() => handleCopy(msg.id, msg.content)}
                          aria-label="Copy response"
                          className="h-7 w-7 inline-flex items-center justify-center rounded-md text-[#9b9b9b] hover:bg-[#EEEEEE] hover:text-[#5a5a5a] transition"
                        >
                          {copiedId === msg.id ? <Check size={14} /> : <Copy size={14} />}
                        </button>
                        {canRegenerate && (
                          <button
                            type="button"
                            onClick={() => handleRegenerate(msg.id)}
                            disabled={isLoading}
                            aria-label="Regenerate response"
                            className="h-7 w-7 inline-flex items-center justify-center rounded-md text-[#9b9b9b] hover:bg-[#EEEEEE] hover:text-[#5a5a5a] disabled:opacity-40 disabled:cursor-not-allowed transition"
                          >
                            <RotateCcw size={14} />
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
              <div ref={messagesEndRef} />
            </div>
          </div>

          {/* Input — sticky to viewport bottom while page scrolls */}
          <div className="sticky bottom-0 z-10 bg-white px-4 pb-3 pt-2 shrink-0">
            <div className="max-w-[768px] mx-auto">
              {InputBox}
              <p className="text-[13px] text-[#b4b4b4] text-center mt-2">
                AI can make mistakes. Please double-check responses.
              </p>
            </div>
          </div>
        </>
      ) : !hasStarted ? (
        /* Inline setup view — add providers, then click Start */
        <div className="flex-1 flex flex-col items-center justify-center px-6 py-10">
          <div className="w-full max-w-[520px]">
            <div className="text-center mb-8">
              <div className="inline-flex items-center justify-center gap-2 mb-4">
                <ProviderLogo provider="openai" size={22} className={PROVIDER_ACCENT.openai} />
                <ProviderLogo provider="anthropic" size={22} className={PROVIDER_ACCENT.anthropic} />
                <ProviderLogo provider="openrouter" size={22} className={PROVIDER_ACCENT.openrouter} />
              </div>
              <h1 className="text-[30px] font-semibold text-[#1c1c1c] mb-2 tracking-tight">
                Connect a provider
              </h1>
              <p className="text-[15px] text-[#5a5a5a] leading-relaxed">
                Add one or more API keys to get started. They stay in your browser.
              </p>
            </div>

            <SettingsContent settings={settings} setSettings={setSettings} variant="inline" />

            <button
              type="button"
              onClick={() => setHasStarted(true)}
              disabled={settings.providers.length === 0}
              className="mt-6 w-full inline-flex items-center justify-center gap-2 h-12 rounded-full bg-[#1c1c1c] text-white text-[15px] font-semibold hover:bg-[#333] transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
            >
              Start chatting
              <ArrowRight size={16} strokeWidth={2.5} />
            </button>
          </div>
        </div>
      ) : (
        /* Empty state: heading + input vertically centered */
        <div className="flex-1 flex flex-col items-center justify-center px-6 pb-6">
          <div className="w-full max-w-[768px]">
            <h1 className="text-[36px] font-semibold text-[#1c1c1c] mb-8 tracking-tight text-center">
              What can I help with?
            </h1>
            {InputBox}
            <p className="text-[13px] text-[#b4b4b4] text-center mt-4">
              AI can make mistakes. Please double-check responses.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
