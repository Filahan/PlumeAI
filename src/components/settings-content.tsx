'use client';

import { useCallback, useState } from 'react';
import { PROVIDER_MODELS, PROVIDER_NAMES, PROVIDER_ACCENT, Provider, Settings, ProviderConfig } from '@/lib/types';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Trash2, Plus, Pencil, Key, Bot, Sparkles } from 'lucide-react';
import { ProviderLogo } from '@/components/provider-logo';

interface ProviderFormProps {
  provider: Provider;
  label: string;
  apiKey: string;
  onProviderChange: (p: Provider) => void;
  onLabelChange: (s: string) => void;
  onApiKeyChange: (s: string) => void;
  onSave: () => void;
  onCancel: () => void;
  submitLabel: string;
}

function ProviderForm({
  provider, label, apiKey, onProviderChange, onLabelChange, onApiKeyChange, onSave, onCancel, submitLabel,
}: ProviderFormProps) {
  return (
    <div className="rounded-xl border border-black/[0.08] bg-white p-3 space-y-3">
      <div className="grid grid-cols-2 gap-2">
        <Select value={provider} onValueChange={(v) => v && onProviderChange(v as Provider)}>
          <SelectTrigger className="h-10 rounded-lg border-black/[0.08] bg-[#FAFAFA] text-[13px] md:text-[13px]">
            <span className="flex items-center gap-2 truncate">
              <ProviderLogo provider={provider} size={14} className={PROVIDER_ACCENT[provider]} />
              {PROVIDER_NAMES[provider]}
            </span>
          </SelectTrigger>
          <SelectContent className="rounded-xl border-black/[0.06] shadow-lg">
            {(Object.keys(PROVIDER_MODELS) as Provider[]).map((p) => (
              <SelectItem key={p} value={p} className="text-[13px] py-2">
                <span className="flex items-center gap-2">
                  <ProviderLogo provider={p} size={14} className={PROVIDER_ACCENT[p]} />
                  {PROVIDER_NAMES[p]}
                </span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Input
          value={label}
          onChange={(e) => onLabelChange(e.target.value)}
          placeholder={`Label e.g. "${PROVIDER_NAMES[provider]}"`}
          className="h-10 rounded-lg border-black/[0.08] bg-[#FAFAFA] text-[13px] md:text-[13px]"
        />
      </div>
      <Input
        type="password"
        value={apiKey}
        onChange={(e) => onApiKeyChange(e.target.value)}
        placeholder="API key (sk-...)"
        className="h-10 rounded-lg border-black/[0.08] bg-[#FAFAFA] text-[13px] md:text-[13px] font-mono"
        autoComplete="off"
      />
      <div className="flex justify-end gap-2 pt-1">
        <Button
          variant="outline"
          onClick={onCancel}
          className="h-9 px-3 rounded-lg border-black/[0.08] text-[13px] font-medium"
        >
          Cancel
        </Button>
        <Button
          onClick={onSave}
          disabled={!apiKey.trim()}
          className="h-9 px-4 rounded-lg bg-[#1c1c1c] text-white text-[13px] font-medium hover:bg-[#333] disabled:opacity-40"
        >
          {submitLabel}
        </Button>
      </div>
    </div>
  );
}

function maskKey(key: string): string {
  if (!key) return '';
  if (key.length < 10) return '•'.repeat(key.length);
  return key.slice(0, 3) + '•'.repeat(8) + key.slice(-4);
}

interface SettingsContentProps {
  settings: Settings;
  setSettings: (s: Settings) => void;
  variant?: 'dialog' | 'inline';
}

export default function SettingsContent({ settings, setSettings, variant = 'dialog' }: SettingsContentProps) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [formProvider, setFormProvider] = useState<Provider>('openai');
  const [formLabel, setFormLabel] = useState('');
  const [formApiKey, setFormApiKey] = useState('');

  // Auto-open the add form when there are no providers yet, so the inline empty state
  // jumps straight into adding the first key without an extra click.
  const showAddForm = editingId === 'new' || (variant === 'inline' && settings.providers.length === 0 && editingId === null);

  const startAddProvider = useCallback(() => {
    setEditingId('new');
    setFormProvider('openai');
    setFormLabel('');
    setFormApiKey('');
  }, []);

  const startEditProvider = useCallback((p: ProviderConfig) => {
    setEditingId(p.id);
    setFormProvider(p.provider);
    setFormLabel(p.label);
    setFormApiKey(p.apiKey);
  }, []);

  const cancelEditProvider = useCallback(() => setEditingId(null), []);

  const saveProvider = useCallback(() => {
    const trimmedKey = formApiKey.trim();
    if (!trimmedKey) return;
    const isNew = editingId === 'new' || editingId === null;
    const next: ProviderConfig = {
      id: isNew ? crypto.randomUUID() : editingId,
      provider: formProvider,
      label: formLabel.trim() || PROVIDER_NAMES[formProvider],
      apiKey: trimmedKey,
    };
    const nextSettings: Settings = isNew
      ? { ...settings, providers: [...settings.providers, next] }
      : { ...settings, providers: settings.providers.map((p) => (p.id === editingId ? next : p)) };
    // If no default model picked yet, default to the first model of the newly added provider.
    if (isNew && nextSettings.providers.length === 1) {
      const firstModel = PROVIDER_MODELS[next.provider]?.[0];
      if (firstModel) {
        nextSettings.defaultModel = { provider: next.provider, model: firstModel };
      }
    }
    setSettings(nextSettings);
    setEditingId(null);
  }, [editingId, formProvider, formLabel, formApiKey, settings, setSettings]);

  const deleteProvider = useCallback((id: string) => {
    setSettings({ ...settings, providers: settings.providers.filter((p) => p.id !== id) });
    if (editingId === id) setEditingId(null);
  }, [settings, setSettings, editingId]);

  const setDefaultModelValue = useCallback((value: string | null) => {
    if (!value) return;
    const [provider, ...rest] = value.split(':');
    const model = rest.join(':');
    setSettings({ ...settings, defaultModel: { provider: provider as Provider, model } });
  }, [settings, setSettings]);

  const defaultModelValue = `${settings.defaultModel.provider}:${settings.defaultModel.model}`;
  const defaultModelOptions: { value: string; label: string }[] = [];
  const seen = new Set<string>();
  for (const p of settings.providers) {
    for (const m of PROVIDER_MODELS[p.provider]) {
      const v = `${p.provider}:${m}`;
      if (seen.has(v)) continue;
      seen.add(v);
      defaultModelOptions.push({ value: v, label: `${PROVIDER_NAMES[p.provider]} · ${m}` });
    }
  }
  if (!seen.has(defaultModelValue)) {
    defaultModelOptions.unshift({
      value: defaultModelValue,
      label: `${PROVIDER_NAMES[settings.defaultModel.provider]} · ${settings.defaultModel.model}`,
    });
  }

  return (
    <div className="space-y-6">
      {/* Providers */}
      <section className="space-y-3">
        <div className="flex items-center gap-2">
          <Key size={15} strokeWidth={2} className="text-[#8e8e8e] shrink-0" />
          <h3 className="text-[13px] font-medium text-[#1c1c1c]">Providers</h3>
        </div>

        {settings.providers.length === 0 && !showAddForm && (
          <p className="text-[13px] text-[#8e8e8e] py-3 px-3 rounded-xl bg-[#FAFAFA] border border-black/[0.06] border-dashed">
            No providers configured yet. Add one to start chatting.
          </p>
        )}

        <div className="space-y-2">
          {settings.providers.map((p) => editingId === p.id ? (
            <ProviderForm
              key={p.id}
              provider={formProvider}
              label={formLabel}
              apiKey={formApiKey}
              onProviderChange={setFormProvider}
              onLabelChange={setFormLabel}
              onApiKeyChange={setFormApiKey}
              onSave={saveProvider}
              onCancel={cancelEditProvider}
              submitLabel="Save"
            />
          ) : (
            <div key={p.id} className="flex items-center gap-3 px-3 py-2.5 rounded-xl border border-black/[0.06] bg-[#FAFAFA]">
              <div className={`w-9 h-9 rounded-lg bg-white border border-black/[0.06] flex items-center justify-center shrink-0 ${PROVIDER_ACCENT[p.provider]}`}>
                <ProviderLogo provider={p.provider} size={18} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-[13px] font-medium text-[#1c1c1c] truncate">{p.label}</div>
                <div className="text-[11px] text-[#8e8e8e] truncate font-mono">
                  {PROVIDER_NAMES[p.provider]} · {maskKey(p.apiKey)}
                </div>
              </div>
              <button
                type="button"
                onClick={() => startEditProvider(p)}
                aria-label="Edit provider"
                className="w-8 h-8 rounded-lg flex items-center justify-center text-[#8e8e8e] hover:bg-[#EEEEEE] hover:text-[#1c1c1c] transition"
              >
                <Pencil size={14} strokeWidth={2} />
              </button>
              <button
                type="button"
                onClick={() => deleteProvider(p.id)}
                aria-label="Delete provider"
                className="w-8 h-8 rounded-lg flex items-center justify-center text-[#9b9b9b] hover:bg-[#EEEEEE] hover:text-[#D43A3A] transition"
              >
                <Trash2 size={14} strokeWidth={2} />
              </button>
            </div>
          ))}

          {showAddForm && (
            <ProviderForm
              provider={formProvider}
              label={formLabel}
              apiKey={formApiKey}
              onProviderChange={setFormProvider}
              onLabelChange={setFormLabel}
              onApiKeyChange={setFormApiKey}
              onSave={saveProvider}
              onCancel={settings.providers.length === 0 ? cancelEditProvider : cancelEditProvider}
              submitLabel="Add"
            />
          )}
        </div>

        {!showAddForm && (
          <button
            type="button"
            onClick={startAddProvider}
            className="w-full flex items-center justify-center gap-2 h-11 rounded-xl border border-dashed border-black/[0.12] text-[13px] font-medium text-[#5a5a5a] hover:bg-[#FAFAFA] hover:text-[#1c1c1c] transition"
          >
            <Plus size={16} strokeWidth={2} />
            Add provider
          </button>
        )}
      </section>

      {/* Default model */}
      {settings.providers.length > 0 && (
        <section className="space-y-2">
          <div className="flex items-center gap-2">
            <Bot size={15} strokeWidth={2} className="text-[#8e8e8e] shrink-0" />
            <h3 className="text-[13px] font-medium text-[#1c1c1c]">Default model</h3>
          </div>
          <Select value={defaultModelValue} onValueChange={setDefaultModelValue}>
            <SelectTrigger className="w-full h-11 rounded-xl border-black/[0.08] bg-[#FAFAFA] hover:bg-[#F5F5F5] transition-colors text-[13px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="rounded-xl border-black/[0.06] shadow-lg">
              {defaultModelOptions.map((o) => {
                const optionProvider = o.value.split(':')[0] as Provider;
                return (
                  <SelectItem key={o.value} value={o.value} className="text-[13px] py-2">
                    <span className="flex items-center gap-2">
                      <ProviderLogo provider={optionProvider} size={14} className={PROVIDER_ACCENT[optionProvider]} />
                      {o.label}
                    </span>
                  </SelectItem>
                );
              })}
            </SelectContent>
          </Select>
          <p className="text-[11px] text-[#a8a8a8] leading-relaxed">
            Used for new conversations. You can change it per-conversation from the chat input.
          </p>
        </section>
      )}

      <p className="text-[11px] text-[#a8a8a8] leading-relaxed pt-1 border-t border-black/[0.05]">
        <Sparkles size={11} className="inline mr-1 -mt-0.5" strokeWidth={2} />
        API keys are stored only in your browser&apos;s local storage. They never reach our servers.
      </p>
    </div>
  );
}
