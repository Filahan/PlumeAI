'use client';

import { useState, useEffect, useRef, useMemo, KeyboardEvent } from 'react';
import { Conversation, Message, Settings, Provider, findApiKey, PROVIDER_MODELS, PROVIDER_NAMES } from '@/lib/types';
import { streamChat, generateTitle } from '@/lib/api';
import { MarkdownRenderer } from '@/components/markdown-renderer';
import { Paperclip, ArrowUp, Copy, Check, RotateCcw, ArrowRight } from 'lucide-react';
import { Select, SelectContent, SelectItem, SelectTrigger } from '@/components/ui/select';
import SettingsContent from '@/components/settings-content';
import { ProviderLogo, PROVIDER_ACCENT } from '@/components/provider-logo';

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

  useEffect(() => {
    if (!conversation) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setDraftProvider(settings.defaultModel.provider);
      setDraftModel(settings.defaultModel.model);
    }
  }, [conversation, settings.defaultModel.provider, settings.defaultModel.model]);

  const activeProvider = conversation?.provider ?? draftProvider;
  const activeModel = conversation?.model ?? draftModel;

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
    if (!input.trim() || isLoading) return;
    const apiKey = findApiKey(settings, activeProvider);
    if (!apiKey) {
      alert(`No API key configured for ${PROVIDER_NAMES[activeProvider]}. Add one in Settings.`);
      return;
    }

    let convId = conversation?.id;
    if (!convId) convId = onCreateConversation(activeProvider, activeModel);

    const userContent = input.trim();
    setInput('');

    const isFirstExchange = (conversation?.messages.length ?? 0) === 0;

    onAddMessage(convId, { role: 'user', content: userContent });
    const assistantMsgId = onAddMessage(convId, { role: 'assistant', content: '' });

    const history = conversation?.messages.map((m) => ({ role: m.role, content: m.content })) ?? [];
    history.push({ role: 'user', content: userContent });

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
    const history = conversation.messages.slice(0, idx).map((m) => ({ role: m.role, content: m.content }));
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

  const InputBox = (
    <div className="bg-[#F4F4F4] rounded-[28px] px-5 pt-4 pb-3.5 transition-shadow focus-within:shadow-[0_0_0_2px_rgba(0,0,0,0.06)]">
      <textarea
        ref={textareaRef}
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Ask anything"
        rows={1}
        className="w-full resize-none bg-transparent text-[17px] text-[#1c1c1c] placeholder:text-[#b4b4b4] outline-none min-h-[28px] max-h-[200px] leading-relaxed"
        disabled={isLoading}
      />

      <div className="flex items-center justify-between mt-2.5 gap-2">
        <div className="flex items-center gap-1 min-w-0">
          <button
            type="button"
            aria-label="Attach file"
            className="w-8 h-8 shrink-0 rounded-full flex items-center justify-center text-[#8e8e8e] hover:bg-[#e8e8e8] hover:text-[#5a5a5a] transition-colors"
          >
            <Paperclip size={16} strokeWidth={1.5} />
          </button>

          <Select value={`${activeProvider}:${activeModel}`} onValueChange={handleModelChange}>
            <SelectTrigger
              aria-label="Choose model"
              className="h-8 max-w-[220px] rounded-full border-transparent bg-transparent hover:bg-[#e8e8e8] text-[13px] font-medium text-[#5a5a5a] px-2.5 gap-1 transition-colors"
            >
              <span className="truncate">
                {availableModels.find((m) => `${m.provider}:${m.model}` === `${activeProvider}:${activeModel}`)?.label ?? activeModel}
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
              disabled={!input.trim()}
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
    <div className="flex flex-col min-h-screen">
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
                    <div className="max-w-[80%] bg-[#F0EAEA] rounded-[20px] px-4 py-2.5 text-[18px] leading-relaxed text-[#1c1c1c] whitespace-pre-wrap break-words">
                      {msg.content}
                    </div>
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
