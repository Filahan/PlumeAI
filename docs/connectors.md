# Connectors

Generated from the live tool catalog (`GET /api/tools`) and the integration schemas in
`apps/api/app/integrations/*`. Every action listed here shows up as a step you can add on the
canvas once its integration is connected.

An action's inputs can each be filled as a **Value**, **From step**, or **Ask AI** field (see
[`docs/automations.md`](automations.md#the-three-ways-to-fill-a-field)) — the "Required inputs"
column below lists the underlying field names an action needs, regardless of how you choose to
fill them.

## Gmail

**Auth:** Google OAuth (shared client — see [Google OAuth setup](automations.md#connecting-tools)). **Credentials namespace:** `google`.

| Action | Required inputs | Optional inputs | Output |
| --- | --- | --- | --- |
| `gmail_search` — Search emails | `query` | `max_results` | `count` plus `messages`: id, thread_id, from, subject, date, and snippet |
| `gmail_get` — Get an email | `id` | — | The message's id, from, to, subject, date, and plain-text body |
| `gmail_send` — Send an email | `to`, `subject`, `body` | `cc`, `bcc` | Confirmation with the sent message id |
| `gmail_modify` — Add or remove labels | `id` | `add_labels`, `remove_labels` | Confirmation of the labels added and removed |
| `gmail_mark_read` — Mark read or unread | `id`, `read` | — | Confirmation of the read/unread state change |
| `gmail_trash` — Trash an email | `id` | — | Confirmation the message was moved to trash |

`gmail_search` uses Gmail's own query syntax (`from:`, `to:`, `subject:`, `label:INBOX`,
`is:unread`, `has:attachment`, `newer_than:1d`, `after:YYYY/MM/DD`, …) — dates must be concrete,
Gmail doesn't understand "today" or "yesterday" literally (which is exactly the kind of wording an
**Ask AI** field resolves for you at run time).

## Google Drive

**Auth:** Google OAuth (same shared client as Gmail/Calendar). **Credentials namespace:** `google`.

| Action | Required inputs | Optional inputs | Output |
| --- | --- | --- | --- |
| `drive_search` — Search files | `query` | `max_results` | `count` plus `files`: id, name, mime_type, and modified_time |
| `drive_get` — Get a file | `id` | — | File metadata plus its plain-text content (Docs/Sheets/Slides exported as text) |
| `drive_list` — List folder contents | — | `folder_id`, `max_results` | Immediate children with id, name, mimeType, and modified time |
| `drive_create_doc` — Create a document | `title`, `content` | — | Confirmation with the new Google Doc's id and name |
| `drive_trash` — Trash a file | `id` | — | Confirmation the file was moved to trash |

`drive_search` uses Drive's own query syntax (`name contains 'roadmap'`,
`mimeType='application/vnd.google-apps.document'`, `trashed=false`, combinable with `and`/`or`).
`drive_list` with no `folder_id` lists the root of My Drive.

## Google Calendar

**Auth:** Google OAuth (same shared client as Gmail/Drive). **Credentials namespace:** `google`.

| Action | Required inputs | Optional inputs | Output |
| --- | --- | --- | --- |
| `calendar_list_events` — List events | — | `time_min`, `time_max`, `q`, `max_results`, `calendar_id` | `count` plus `events`: id, summary, start, end, location, attendee count, link |
| `calendar_get_event` — Get an event | `id` | `calendar_id` | Full event details: summary, time, attendees, and description |
| `calendar_create_event` — Create an event | `summary`, `start`, `end` | `description`, `location`, `attendees`, `calendar_id` | Confirmation with the new event's id and link |
| `calendar_update_event` — Update an event | `id` | `summary`, `start`, `end`, `description`, `location`, `attendees`, `calendar_id` (only the fields you pass are changed) | Confirmation the event was updated |
| `calendar_delete_event` — Delete an event | `id` | `calendar_id` | Confirmation the event was deleted |

Dates must be concrete RFC3339 strings — `YYYY-MM-DDTHH:MM:SS` with a timezone offset for timed
events, or `YYYY-MM-DD` for all-day events; never the literal words "today"/"tomorrow"/"now"
(again, exactly what an **Ask AI** field is for). Defaults for `calendar_list_events`:
`time_min` = now, `time_max` = now + 7 days, `calendar_id` = `primary`.

## Slack

**Auth:** Bot token (`xoxb-…`). **Credentials namespace:** `slack`.

| Action | Required inputs | Optional inputs | Output |
| --- | --- | --- | --- |
| `slack_list_channels` — List channels | — | `types`, `limit` | Channels visible to the bot, with id, name, privacy, member count, and topic |
| `slack_send_message` — Send a message | `channel`, `text` | `thread_ts` (reply in a thread) | The channel id and the message timestamp (`ts`), plus a permalink |
| `slack_read_messages` — Read messages | `channel` | `limit`, `oldest` | Recent messages, oldest first, with ts, author id, author name, and text |

`channel` accepts either a channel id (`C0123456789`) or a name with a leading `#`
(`#general`). The bot must be a member of a channel to post in or read from it — invite it with
`/invite @YourBot` in Slack. Private channels are invisible to the bot until invited, even with
the right scopes.

## Discord

**Auth:** Bot token. **Credentials namespace:** `discord`.

| Action | Required inputs | Optional inputs | Output |
| --- | --- | --- | --- |
| `discord_list_guilds` — List servers | — | — | Servers (guilds) the bot has been invited to, with id and name |
| `discord_list_channels` — List channels | `guild_id` | — | Channels in the server with id, name, and type |
| `discord_list_messages` — Read messages | `channel_id` | `limit` | Recent messages with author, content, and timestamp, most recent first |
| `discord_send_message` — Send a message | `channel_id`, `content` | — | Confirmation with the sent message id |

The bot only sees channels it's been granted access to. PlumeAI shows a one-click invite link once
the bot token is saved and reachable (Tools → Discord → "Invite to a Discord server").

## Notion

**Auth:** Internal integration secret (`ntn_…` / `secret_…`). **Credentials namespace:** `notion`.

| Action | Required inputs | Optional inputs | Output |
| --- | --- | --- | --- |
| `notion_search` — Search pages | `query` | `filter`, `limit` | Matching pages/databases with id, title, url, last edited time, and whether more matches exist |
| `notion_get_page` — Read a page | `page_id` | — | The page title, url, flattened properties, its text content, and whether it had more blocks than were read |
| `notion_create_page` — Create a page | `parent_id`, `title` | `parent_type`, `content` (markdown), `properties` (for a database row) | The new page's id, title, and url |
| `notion_append_blocks` — Append to a page | `page_id`, `content` (markdown) | — | How many blocks were appended |
| `notion_query_database` — Query a database | `database_id` | `filter`, `sorts` (Notion's own filter/sort JSON shapes), `page_size` | Matching rows with id, url, and flattened properties, plus whether more pages exist |

`content` accepts a subset of markdown (headings, bullets, numbered lists, quotes, code fences,
paragraphs) — inline formatting like `**bold**` is written literally, not converted. A page or
database not explicitly shared with the integration is invisible to every action here, even with
a valid token; share it from Notion's "…" menu → Connections.

## Built-in (no setup required)

| Action | Required inputs | Optional inputs | Output |
| --- | --- | --- | --- |
| `web_search` — Search the web | `query` | — | Top results with title, url, and snippet |
| `web_fetch` — Fetch a web page | `url` | — | The fetched `url`, the page `title`, and its readable `text` |
| `http` — HTTP request | `method`, `url` | `body`, `headers` | The response `status`, a subset of its `headers`, and `body` (parsed JSON when the response is JSON, otherwise text) |

Every user-supplied URL passed to `web_fetch`/`http` is checked against private/loopback/link-local
address ranges before the request is made (see [`docs/security.md`](security.md)).

## MCP servers

Any MCP server you register (Tools → Custom tools) contributes its own tools as actions under the
integration `mcp:<server-name>`, named `mcp__<server-name>__<tool-name>`. Their input/output
schemas come from the server itself rather than from PlumeAI, so they aren't listed here — the
step picker and the inspector read them live from what the server advertises. See
[`docs/automations.md`](automations.md#adding-an-mcp-server) for how to add one, and
[`docs/architecture.md`](architecture.md#mcp-integration) for how PlumeAI talks to it.
