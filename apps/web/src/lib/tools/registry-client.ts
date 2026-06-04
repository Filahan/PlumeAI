/** Client-safe subset of the tool registry. Never imports server code so the bundle stays small
 *  and no secrets leak. Used by the @ mention autocomplete and the Settings UI. */

export interface CredentialField {
  name: string;
  label: string;
  secret: boolean;
  placeholder?: string;
}

export interface SetupStepLink {
  label: string;
  url: string;
}

export interface SetupStepCopy {
  label: string;
  /**
   * Value displayed with a copy button. If it contains the literal token
   * `__ORIGIN__`, the renderer substitutes `window.location.origin` at runtime.
   */
  value: string;
}

export interface SetupStep {
  title: string;
  description?: string;
  link?: SetupStepLink;
  copy?: SetupStepCopy;
  code?: string;
}

export interface ToolSetup {
  intro: string;
  steps: SetupStep[];
  /** Small footer note — scopes requested, privacy reminder, etc. */
  note?: string;
}

export interface ToolDescriptor {
  name: string;
  label: string;
  description: string;
  /** OAuth start URL — only meaningful when `connectMode === 'oauth'`. */
  setupUrl: string;
  /**
   * How the user "connects" this tool.
   * - `oauth` (default): clicking Connect navigates to `setupUrl` to begin OAuth.
   * - `config`: tool is enabled once credentials are saved (no per-user OAuth).
   */
  connectMode?: 'oauth' | 'config';
  /** Absolute URL of a brand logo (svg). Falls back to a generic icon when omitted. */
  logoUrl?: string;
  /**
   * Namespace used to look up app-level credentials in `settings.toolCredentials`.
   * Several integrations sharing the same OAuth client (Gmail/Drive/Calendar) share
   * the same namespace ("google").
   */
  credentialsNamespace?: string;
  /** Input fields shown in the credentials section of the modal. */
  credentialsFields?: CredentialField[];
  /** Long-form setup guide (how to obtain those credentials). */
  setup: ToolSetup;
}

const GOOGLE_CREDENTIALS_FIELDS: CredentialField[] = [
  {
    name: 'client_id',
    label: 'OAuth Client ID',
    secret: false,
    placeholder: '123-abc.apps.googleusercontent.com',
  },
  {
    name: 'client_secret',
    label: 'OAuth Client Secret',
    secret: true,
    placeholder: 'GOCSPX-...',
  },
];

const GOOGLE_OAUTH_STEPS: SetupStep[] = [
  {
    title: 'Create an OAuth client in Google Cloud Console',
    description: 'Pick "Web application" as the type. Reuse an existing client if you have one.',
    link: {
      label: 'Open Credentials',
      url: 'https://console.cloud.google.com/apis/credentials',
    },
  },
  {
    title: 'Add this URL to your OAuth client\'s "Authorized redirect URIs"',
    copy: {
      label: 'Authorized redirect URI',
      value: '__ORIGIN__/api/tools/google/oauth/callback',
    },
  },
  {
    title: 'Paste the generated Client ID and Client Secret into the Credentials section above',
    description:
      'One credential pair unlocks Gmail, Drive, Calendar, and every future Google integration.',
  },
];

const GOOGLE_SETUP: ToolSetup = {
  intro:
    'Uses Google OAuth — set up the OAuth client once, share it across every Google integration.',
  steps: GOOGLE_OAUTH_STEPS,
};

const DISCORD_SETUP: ToolSetup = {
  intro:
    'Discord uses a bot token. Create a bot once in the Discord Developer Portal and paste the token above.',
  steps: [
    {
      title: 'Create a Discord application',
      description: 'Pick a name (e.g. "PlumeAI bot").',
      link: {
        label: 'Open Discord Developer Portal',
        url: 'https://discord.com/developers/applications',
      },
    },
    {
      title: 'Enable the Bot and copy its token',
      description:
        'In the "Bot" tab, click "Reset Token" and copy the value — it is shown only once. Paste it into the Credentials section above.',
    },
    {
      title: 'Invite the bot to your server',
      description:
        'OAuth2 → URL Generator → scope "bot" + permissions (Send Messages, Read Message History). Open the generated URL and pick the server.',
    },
  ],
  note: 'Privileges: Send Messages, Read Message History. The bot can only see channels you grant it access to.',
};

// Logos come from simple-icons CDN — colored variant via /<slug>/<hex>.
export const TOOL_DESCRIPTORS: readonly ToolDescriptor[] = [
  {
    name: 'gmail',
    label: 'Gmail',
    description: 'Read, send, label, and trash Gmail messages.',
    setupUrl: '/api/tools/gmail/oauth/start',
    logoUrl: 'https://cdn.simpleicons.org/gmail',
    credentialsNamespace: 'google',
    credentialsFields: GOOGLE_CREDENTIALS_FIELDS,
    setup: GOOGLE_SETUP,
  },
  {
    name: 'drive',
    label: 'Google Drive',
    description: 'Search, read, list, create, and trash files on Google Drive.',
    setupUrl: '/api/tools/drive/oauth/start',
    logoUrl: 'https://cdn.simpleicons.org/googledrive',
    credentialsNamespace: 'google',
    credentialsFields: GOOGLE_CREDENTIALS_FIELDS,
    setup: GOOGLE_SETUP,
  },
  {
    name: 'calendar',
    label: 'Google Calendar',
    description: 'Read, create, update, and delete events on Google Calendar.',
    setupUrl: '/api/tools/calendar/oauth/start',
    logoUrl: 'https://cdn.simpleicons.org/googlecalendar',
    credentialsNamespace: 'google',
    credentialsFields: GOOGLE_CREDENTIALS_FIELDS,
    setup: GOOGLE_SETUP,
  },
  {
    name: 'discord',
    label: 'Discord',
    description: 'Send messages, read messages, and list channels in Discord servers.',
    setupUrl: '',
    connectMode: 'config',
    logoUrl: 'https://cdn.simpleicons.org/discord',
    credentialsNamespace: 'discord',
    credentialsFields: [
      {
        name: 'bot_token',
        label: 'Bot Token',
        secret: true,
        placeholder: 'MTAxxx.Gxxxx.xxxxx',
      },
    ],
    setup: DISCORD_SETUP,
  },
] as const;

export function findToolDescriptor(name: string): ToolDescriptor | undefined {
  return TOOL_DESCRIPTORS.find((t) => t.name === name);
}
