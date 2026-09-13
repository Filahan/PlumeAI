"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.PROVIDER_ACCENT = exports.PROVIDER_BASE_URLS = exports.PROVIDER_NAMES = exports.PROVIDER_MODELS = void 0;
exports.findApiKey = findApiKey;
function findApiKey(settings, provider) {
    return settings.providers.find((p) => p.provider === provider)?.apiKey ?? '';
}
exports.PROVIDER_MODELS = {
    openai: ['gpt-4o', 'gpt-4o-mini', 'gpt-4.1', 'gpt-4.1-mini'],
    anthropic: ['claude-3-7-sonnet-20250219', 'claude-3-5-sonnet-20241022', 'claude-3-5-haiku-20241022'],
};
exports.PROVIDER_NAMES = {
    openai: 'OpenAI',
    anthropic: 'Anthropic',
};
exports.PROVIDER_BASE_URLS = {
    openai: 'https://api.openai.com/v1',
    anthropic: 'https://api.anthropic.com/v1',
};
exports.PROVIDER_ACCENT = {
    openai: 'text-[#10A37F]',
    anthropic: 'text-[#D97757]',
};
