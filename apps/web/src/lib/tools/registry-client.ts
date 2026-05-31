/** Client-safe subset of the tool registry. Never imports server code so the bundle stays small
 *  and no secrets leak. Used by the @ mention autocomplete and the Settings UI. */

export interface ToolDescriptor {
  name: string;
  label: string;
  description: string;
  setupUrl: string;
  /** Absolute URL of a brand logo (svg). Falls back to a generic icon when omitted. */
  logoUrl?: string;
}

// Logos come from simple-icons CDN — colored variant via /<slug>/<hex>.
export const TOOL_DESCRIPTORS: readonly ToolDescriptor[] = [
  {
    name: 'gmail',
    label: 'Gmail',
    description: 'Read, send, label, and trash Gmail messages.',
    setupUrl: '/api/tools/gmail/oauth/start',
    logoUrl: 'https://cdn.simpleicons.org/gmail/EA4335',
  },
] as const;

export function findToolDescriptor(name: string): ToolDescriptor | undefined {
  return TOOL_DESCRIPTORS.find((t) => t.name === name);
}
