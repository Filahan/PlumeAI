import 'server-only';

import { PROVIDER_BASE_URLS, type Provider } from '@/lib/types';
import { resolveProviderKey } from '@/lib/agent/run';

const SYSTEM_PROMPT =
  'You generate a concise 3-5 word title for an automation task. ' +
  "Reply with ONLY the title text — no quotes, no punctuation, no prefix, in the user's language.";

/** Best-effort task title from the user's first-message intent. Returns '' on failure so the
 *  caller can fall back to the prompt-derived label without surfacing an error. */
export async function generateTaskTitle(
  provider: Provider,
  model: string,
  userIntent: string
): Promise<string> {
  if (provider === 'anthropic') return '';
  let apiKey: string;
  try {
    apiKey = await resolveProviderKey(provider);
  } catch {
    return '';
  }

  try {
    const res = await fetch(`${PROVIDER_BASE_URLS[provider]}/chat/completions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${apiKey}` },
      body: JSON.stringify({
        model,
        max_tokens: 40,
        messages: [
          { role: 'system', content: SYSTEM_PROMPT },
          { role: 'user', content: userIntent },
        ],
      }),
    });
    if (!res.ok) return '';
    const data = (await res.json()) as { choices?: Array<{ message?: { content?: string } }> };
    const raw = data.choices?.[0]?.message?.content ?? '';
    // Strip wrapping quotes / trailing punctuation if the model misbehaves.
    return raw.trim().replace(/^["'`]+|["'`.!?]+$/g, '').slice(0, 80);
  } catch {
    return '';
  }
}
