# Building automations

This is a plain-language guide to building automations in PlumeAI. No coding required.

## What an automation is

An automation is one **trigger** (what starts it) followed by a list of **steps** that run in
order, top to bottom. Each step can use what an earlier step produced. There are no branches and
no loops — just a straight list, which makes it easy to read top to bottom and know exactly what
will happen.

## Creating an automation with the assistant

The fastest way to start is to describe what you want in a sentence, on the home screen:

> Every weekday at 8:00, summarize unread emails from my boss and post it to Discord

Press Create (or hit Enter). PlumeAI creates a blank automation, opens it, and the assistant reads
your sentence and builds the trigger and the steps for you. You'll see it work in the Assistant
panel on the right, and the canvas fill in as it goes.

You don't have to describe everything up front. A few other things you can say to the assistant,
any time:

- "Search the web for news about **electric bikes** every morning and email me a digest" — fill
  in the blank yourself before sending.
- "Why did the last run fail?" — the assistant answers from the automation's run history; it
  won't change anything for a question like this.
- "Add a step that also posts to Slack after the summary" — it edits the existing automation
  rather than starting over.

The assistant never hides what it did behind vague language. After a change, it shows a short
"Applied" list of what it actually changed, and an **Undo** button that reverts the document to
right before that turn — as long as nothing has been changed since.

If you asked it to run or test the automation, it does that too, and gives you a link to watch
the run.

## The canvas

Once an automation is open, the canvas shows it as a vertical list: the **Trigger** card at the
top, then one card per step below it, in the order they run. Click any card to open its settings
in the panel on the right (the **inspector**).

- **Add a step** — click any "+" between two cards, at the bottom of the list, or use the empty
  state's "Add a step" button if the automation has none yet. This opens a search dialog over
  every connected (and not-yet-connected) tool, plus AI steps and filters.
- **Reorder** — the canvas itself isn't drag-and-drop; to change the order of steps, ask the
  assistant to reorder them, or switch to the JSON view and move the step there.
- **Delete a step** — select it, then press Delete/Backspace or the trash icon in the inspector.
  It arms first ("press again to confirm") so you can't remove a step by accident.
- **Rename a step or the automation** — click the name to edit it in place.
- A small red dot on a card means it needs attention — usually a missing required field, or an
  action whose integration is no longer connected.

## Adding a step

When you open the step picker, tools are grouped by name, with actions listed underneath. A tool
you haven't connected yet still shows up — the row is dimmed with a "Connect" shortcut, so you
can plan an automation before every tool it needs is ready. There are also two special entries:

- **AI step** — "let the model read earlier steps and write the result."
- **Filter** — "stop the run here unless a condition holds."

## The three ways to fill a field

Every setting of an action step (a Gmail search query, a Slack channel, an email's subject) can be
filled one of three ways. Switch between them with the small **Value / From step / Ask AI**
toggle above each field:

- **Value** — you type the value in yourself. Use this for anything fixed: a channel name, a
  recipient, a number.

  Example: the Slack channel field set to `#team-updates`.

- **From step** — point at something an earlier step produced. Click the button to open a picker
  that lists every earlier step and the fields it's known to return (or, if it's never run yet,
  lets you type the path by hand). This is the right choice when a value is *exactly* what came
  out of a previous step — no rewording needed.

  Example: an email's body field set to "the summary from the Summarize step" — picked from the
  list, which turns into `{{step_p2m7c.output.summary}}` behind the scenes. You never have to
  type that yourself; the picker does it.

- **Ask AI** — describe in a sentence what should go there, and a model fills it in every time
  the automation runs. Use this whenever a value depends on wording, judgment, or combining
  several things — not just copying a single earlier result. This is what makes automations work
  without needing to know any kind of expression syntax.

  Example: a Gmail search query field set to "unread emails from my boss since yesterday" — the
  AI turns that into an actual, correctly-dated Gmail search query at run time.

**Rule of thumb:** use **Ask AI** by default whenever the value isn't a hard constant, **From
step** when you want an earlier result passed through untouched, and **Value** for real constants
(a channel, an email address, a limit).

## AI steps

An AI step doesn't call a specific tool by itself — instead, you write an instruction ("Summarize
the emails above in three bullet points") and, optionally, let it call some of your connected
tools while it works (for instance, letting it fetch one more email if it needs to). You choose
what it hands back:

- **Plain text** — a paragraph or a few bullet points, which you can then reference from a later
  step.
- **Structured fields** — you define named fields (a summary string, a boolean flag, …) and the AI
  fills them in; later steps can then reference each field individually, like
  `{{step_id.output.summary}}` rather than the whole block of text.

## Filters

A filter stops the automation right there unless something holds — every step after it is
skipped, and the run still finishes normally (it isn't treated as a failure). You have two ways to
write the condition:

- **Check some rules** — compare a value to another: equals, doesn't equal, greater/less than,
  contains, is empty, is true/false, and so on. You can require **all** rules to match, or
  **any** one of them.
- **Ask the AI to decide** — write the condition as a sentence ("Continue only if the email is
  urgent") and the AI answers yes or no each time the run reaches that point.

## Schedules

The trigger decides when (or whether) an automation runs on its own:

- **When I press Run** — nothing happens automatically; you (or the assistant, when testing) start
  it by hand.
- **Every few minutes** — a simple repeating interval (with quick picks: 5, 15, 30, or 60
  minutes), useful for polling something frequently.
- **On a schedule** — a specific time, using presets: every hour (pick the minute), every day at a
  time you choose, weekdays only, once a week on a chosen day, or a custom cron expression if you
  need something the presets don't cover.

Every schedule has a **timezone**, shown right next to the frequency, and the inspector shows you
the next few times it will actually fire so you can double-check it before saving. If a schedule
doesn't set its own timezone, it uses your workspace timezone (Settings → Timezone).

## Running and testing

Press **Run now** in the top bar to start the automation immediately. While a run is in progress,
the button becomes **Cancel**. The assistant can also start a run for you when you ask it to test
something.

## Reading run results

Open the **Runs** panel (the History button) to see every past run and select one. For the
selected run you'll see, per step:

- its status (waiting, running, succeeded, failed, skipped, or cancelled),
- how long it took,
- the input it actually used, once it's resolved (any secret-looking field is hidden),
- what it produced,
- and — for AI steps — a trace of what it said and which tools it called along the way.

If a run is happening right now, this all updates live as it happens — you don't need to refresh.
If a filter stopped the run, you'll see exactly which step stopped it and why.

## Undo and version history

Every change you make — through the canvas, the assistant, or the JSON view — creates a new,
numbered version of the automation. Nothing is ever silently overwritten. The assistant's own Undo
button reverts the document to right before its last turn; for anything older, open the version
history to see every past version and restore one if you need to.

## The JSON view

If you're comfortable with JSON, the **Design / JSON** toggle at the top switches to a raw text
editor of the whole document. It's parsed as you type — invalid JSON just shows an error and
doesn't touch your saved automation until you fix it and hit **Apply**. This is useful for making
several related edits at once, or for copying settings between steps.

## Connecting tools

Go to the **Tools** page to connect the accounts your automations need. Each tool's card walks you
through what to do — most of the setup work happens outside PlumeAI, in the tool's own developer
console, because that's simply how these services issue credentials:

- **Gmail, Google Drive, Google Calendar** — these three share one Google OAuth client. You
  create it once in the Google Cloud Console (a few minutes: create an OAuth client, paste in a
  redirect URL PlumeAI shows you, then paste the generated Client ID and Client Secret back into
  PlumeAI), and after that connecting Drive or Calendar is a one-click "Connect" — no second setup.
- **Slack** — create a Slack app, add a handful of bot permissions ("scopes"), install it to your
  workspace, and paste the bot token (starts with `xoxb-`) into PlumeAI. Afterward, in Slack, run
  `/invite @YourBotName` in each channel you want it to read from or post to — a bot can't see a
  channel it hasn't been invited to, even a public one.
- **Discord** — create a bot in the Discord Developer Portal, copy its token into PlumeAI, then
  use the "Invite to a Discord server" button PlumeAI shows you once the token is saved, so you
  never have to build that invite link yourself.
- **Notion** — create an "internal integration" in Notion, copy its secret into PlumeAI, then go
  back into Notion and share each page or database you want it to reach with that integration
  (sharing a parent page also shares everything nested under it). A page you haven't shared stays
  invisible to PlumeAI even with a valid token — this is the most common reason a Notion search
  comes back empty.

Every card has a **How to obtain these credentials** section with the exact steps and links you
need, so you don't have to leave PlumeAI to find them.

## Adding an MCP server

Beyond the built-in tools, PlumeAI can use any [MCP](https://modelcontextprotocol.io) server —
useful for a tool PlumeAI doesn't support directly. On the Tools page, under "Custom tools," click
**Add MCP server** and give it:

- a short name (this becomes part of how its tools show up in the step picker),
- either a **command** to run (for a server that speaks over stdio — for example
  `uvx mcp-server-time`) or a **URL** (for a server reachable over HTTP),
- any environment variables or headers it needs (API keys, for instance) — these are write-only
  once saved, so you'll see "set" rather than the value again.

Use **Test connection** before saving to make sure PlumeAI can actually reach it and see its
tools. Once added, its tools appear in the step picker and the AI step's tool list just like any
other connector.
