# Automations UX audit

Date: 2026-05-31
Scope: `/automations` flow (composer → interview → skill → run) + the `/tools` integration handshake.

## Executive summary

The Automations flow is conceptually strong — the LLM interviewer is genuinely useful and the @-mention pattern is elegant. But three issues create disproportionate friction for new and returning users:

1. **The schedule selector lies.** `manual / hourly / daily / weekly` is wired into UI and DB, yet no scheduler ever fires. This trains users to distrust the product.
2. **Empty state offers zero guidance.** First-time users land on a blank textarea with no examples, no list of available tools, no idea what's possible.
3. **Provider/key dead-ends.** Selecting Anthropic, or starting without an OpenAI/OpenRouter key, fails only AFTER the user has typed a prompt and clicked Start — a costly dead-end.

Fixing these three covers ~70% of the perceived friction. The full ranked proposal list is at §5.

---

## 1. Journey map

| # | State | Decision / action | Emotional valence | Key code |
|---|---|---|---|---|
| 1 | Lands on `/automations` empty | Sees blank textarea + model + "Start interview" | 😐 neutral → 😕 confused (no prompt examples) | `automations-view.tsx` TaskComposer ~l.135-200 |
| 2 | Types intent → clicks Start | Component switches to chat mode | 🙂 anticipation | `start()` in TaskComposer + `use-automations.ts` `chat` |
| 3 | Sees first Q with options | Clicks an option → auto-sent | 😊 satisfaction (snappy) | `MessageBubble` + `send()` |
| 4 | Q&A loop (3-6 questions) | Picks options or types answers | 😐 mild fatigue around Q4-5 | `InterviewChat` ~l.215-345 |
| 5 | "Skill ready." + textarea swap | Reads skill, may edit | 🙂 sense of progress | `SkillReady` ~l.378-491 |
| 6 | Clicks Run | SSE transcript appears below skill | 🙂 → 😟 when 1st tool errors | `runTask` in `use-automations.ts` |
| 7 | Done — result rendered | Maybe re-runs, schedules, closes tab | 😐 → 😕 (schedule does nothing) | `TaskList` row + schedule dot |

The valence drops sharply at states 1 and 7 — entrance and exit, the two most memorable moments.

---

## 2. Heuristic evaluation (Nielsen)

| # | Heuristic | Violation | Where |
|---|---|---|---|
| 1 | Visibility of status | Run transcript stream OK; but "Thinking…" pendant l'interview ne dit pas QUOI le LLM fait (parse JSON? appel API?) | `InterviewChat` ~l.293 |
| 2 | Match between system & real world | `after:today` regression (fixed) + skill text exposes function names like `gmail_search` to end user (technical leak) | `interview.ts` system prompt + skill samples |
| 3 | User control & freedom | **No way to restart an interview** — only "delete task". Also pas de "Stop generation" pendant que le LLM répond une question | `InterviewChat` |
| 4 | Consistency & standards | Composer button = "Start interview" mais une fois en chat, Send envoie un message — vocabulary shift sans transition | TaskComposer vs InterviewChat |
| 5 | Error prevention | **Sélectionner Anthropic dans le model picker n'avertit pas** que l'interview va échouer (Anthropic interdit côté serveur) | `interview.ts:37-39` + ModelSelect |
| 6 | Recognition vs recall | L'utilisateur doit **se souvenir** des outils dispos pour @mention (pas de chip cliquable, juste le popup au @) | `TaskComposer` empty state |
| 7 | Flexibility / efficiency | Cmd+Enter pour envoyer ? Non — seulement Enter (sans Shift). Aucun raccourci sur l'écran ready (Cmd+Enter to Run ?) | InterviewChat onKeyDown |
| 8 | Aesthetic minimalism | Le `<details>` "View interview" devient bruyant après 3-4 runs ; le bloc Result n'a pas de `<h2>` sémantique | `SkillReady` ~l.450 |
| 9 | Help users recognize errors | `chatError` s'affiche en petit rouge en bas, sans suggestion d'action ("Open Settings", "Reconnect Gmail") | `InterviewChat` error block |
| 10 | Help & docs | Aucune doc inline / tooltip sur "qu'est-ce qu'un skill ?" "que veut dire @ ?" | Partout |

---

## 3. Friction list (P0/P1/P2)

### P0 (block trust or completion)

- **P0-1 — Schedule selector is cosmetic.** `manual/hourly/daily/weekly` exists but no scheduler tourne. L'utilisateur règle "daily" et croit que ça va tourner. Massive trust killer. _Files: `automations-view.tsx` ScheduleSelect ~l.566, `types.ts` TaskSchedule._
- **P0-2 — Empty state is hostile.** Blank textarea, no examples, no tool list. Users don't know what to type. _Files: `TaskComposer` ~l.135-200._
- **P0-3 — Provider dead-end.** Anthropic or missing-key produces a tiny red line only AFTER the user types + clicks Start. _Files: `TaskComposer.start` + `interview.ts:37-39`._

### P1 (notable friction)

- **P1-1 — No way to restart interview.** Wrong path = delete the task. _Files: `InterviewChat`._
- **P1-2 — @-mention popup is the only entry point.** Without typing @, the user never discovers Gmail exists. _Files: `MentionAutocomplete` + composer placeholder._
- **P1-3 — Unconnected tool referenced → no inline "Connect" CTA.** Interviewer just says "go to Settings". _Files: `interview.ts` system prompt._
- **P1-4 — Run transcript piles up inside the skill card.** After 2 runs the card is unreadable. _Files: `SkillReady` ~l.460._
- **P1-5 — `MentionAutocomplete` uses a 80ms polling loop on `selectionStart`.** Functional but battery-/jank-suboptimal — `selectionchange` event would suffice. _File: `mention-autocomplete.tsx`._

### P2 (polish / debt)

- **P2-1 — Task list lacks "last run at" + quick re-run button.** Users return to a task and have to re-open it to see when it last ran. _File: `TaskList`._
- **P2-2 — Status dots are color-only.** `bg-[#10A37F]` for succeeded etc. Not screen-reader-friendly, fails for color-blind users. _File: `TASK_STATUS_DOT` map._
- **P2-3 — "Result" header is a small uppercase 11px label.** Easy to lose between tool cards. Should be `<h2>` semantic. _File: `SkillReady` ~l.452._
- **P2-4 — Skill textarea has no syntax highlight / @-mention chip.** The @gmail inside the skill is plain text. _File: `SkillReady` textarea._
- **P2-5 — Timezone hint.** Today's date injected server-side as `toISOString().slice(0,10)` = UTC. A user in PT clicking at 23:00 PT gets tomorrow's date. _File: `run.ts` + `interview.ts` `todayIso()`._
- **P2-6 — No undo on option click.** Click an option by accident → message sent → interview moves on. _File: `MessageBubble` onPick._

---

## 4. Accessibility checks

- `MentionAutocomplete` popup should be `role="listbox"` with `aria-activedescendant` on the textarea. Currently rendered as `<div><button>` — keyboard nav works but screen readers won't announce options.
- Multiple-choice option buttons in `MessageBubble` are rendered as buttons without a container `role="group"` and no `aria-label="Suggested answers"`.
- Task status (`TASK_STATUS_DOT`) is communicated only by background color. Add a hidden text label or aria-label per row.
- Focus is lost after the interview finalizes — the skill textarea should receive autofocus.
- "Thinking…" placeholder lacks `aria-live="polite"` so screen readers won't announce the wait.
- `MentionAutocomplete` floats above the textarea but isn't trapped in focus — Tab from the textarea jumps past the popup.
- 11px muted gray text (e.g. `text-[color:var(--muted-foreground)]`) likely fails WCAG AA contrast for body text. Audit with the actual hex.

---

## 5. Ranked proposals

### 🥇 P1: Empty-state seeds + tool chips (P0-2 + P1-2)

**Problem.** Empty textarea kills first-use discovery.

**Change.** When `task.messages.length === 0` AND no draft typed, show:
- 2-3 starter prompt chips ("Daily HN top stories", "Summarize today's Gmail", "Watch a URL for changes") — click = pre-fills the textarea.
- A row of available integration chips ("@gmail" + future ones) under the textarea, with a "Connect" badge if not configured.

**Why.** Discoverability + perceived velocity. Users see immediately what the tool can do.

**Files.** `TaskComposer` in `automations-view.tsx` + `TOOL_DESCRIPTORS` from `registry-client.ts`. ~50 lines.

### 🥈 P2: Honest schedule UX (P0-1)

**Problem.** Schedule selector implies the task will run automatically. It won't.

**Change.** Two options:
- **A (preferred, smallest):** Rename labels to add "(manual today)" suffix until scheduler ships. Add a subtle banner: "Scheduling is in preview — only Manual triggers run for now."
- **B (real fix, more work):** Implement a node-cron scheduler inside the dev container (the user picked self-host Docker, so a process-resident cron works). One small file, ~50 lines.

**Why.** Stops training distrust.

**Files.** `ScheduleSelect` labels + a banner in `SkillReady`. ~10 lines for A; ~80 for B.

### 🥉 P3: Provider guardrail at the composer (P0-3)

**Problem.** User types intent → clicks Start → silent or red-line failure because provider is Anthropic or key missing.

**Change.** In `TaskComposer`:
- If selected model is Anthropic, **disable Start** with tooltip: "Tool-using tasks need OpenAI or OpenRouter — pick another model".
- If `apiKey` empty, the existing red message becomes a button: **"Open Settings to add a key"**.
- Pre-filter the model select to only providers that have a configured key (with a sub-label "(no key)" instead of grayed out for clarity).

**Why.** Error prevention > error recovery.

**Files.** `TaskComposer` ~l.190-200 + `ModelSelect`. ~30 lines.

---

### Next 9 (one-liner per proposal)

4. **"Restart interview" button** in InterviewChat header — keeps task ID, clears messages + prompt, sends nothing until user re-types.
5. **Inline "Connect tool" CTA in interview chat** when `@gmail` appears but Gmail isn't configured. The interviewer's "go to Settings" becomes a clickable bubble that opens `/tools` in a new tab.
6. **Collapse the run transcript** in SkillReady — show only the final result by default, "View execution (8 steps)" details below the skill, mirroring "View interview".
7. **Replace `setInterval(80)` cursor poll** in `MentionAutocomplete` with `document.addEventListener('selectionchange')` scoped to the textarea (better perf, instantaneous).
8. **Add "last run at" + quick Run icon** to each TaskList row. Hover reveals duration ("ran 2 min ago in 4.3 s").
9. **Add an iconography layer to status dots** (✓ for succeeded, ⚠️ for failed, ⟳ animated for running) so it's not color-only.
10. **Cmd/Ctrl+Enter shortcut** to Send/Run from any of the three textareas. Show the hint in placeholder.
11. **Timezone-aware "today"** — pass the user's TZ in a header from the client, compute `today` server-side in that TZ before injecting in system prompts.
12. **"Why this question?" tooltip** on each interviewer Q. Click reveals which of the 5 dimensions (source, action, output, auth, schedule) it's covering. Reduces interview fatigue.

---

## 6. A/B-able experiments (top 3)

| Proposal | Hypothesis | Variants | Metric (over 2 weeks) |
|---|---|---|---|
| 1 (seeds) | Showing 3 starter prompts increases first-task completion by ≥30% | A: current blank / B: 3 starter chips + tool row | % new users who reach state 6 (Run) within session |
| 2A (label) | Adding a "preview" suffix to schedule reduces support questions about "why my task didn't run" | A: current "Daily" / B: "Daily (preview)" + banner | # of /automations sessions where schedule != manual AND task is never re-opened |
| 3 (guardrail) | Disabling Start when model is incompatible reduces failed-interview rate by ≥80% | A: current / B: disabled button + tooltip | % of interviews that finalize successfully |

For a small team / solo dev, "A/B" can simply be a one-week toggle in a config flag — no traffic split needed.

---

## 7. Out of scope (noted, not addressed here)

- The Tools page setup guide (Gmail OAuth) is its own UX subtree — covered separately in the in-progress "unverified app" + "enable Gmail API" guide updates.
- Multi-user sharing of automations — currently single-user; the `ownerId` column exists but is unused.
- Error recovery for partial Gmail token loss (revoked by Google) — handled at the technical layer (refresh-on-401 retry), but no UX surface yet.

---

## Methodology note

This audit was conducted by reading the implementation end-to-end and applying Nielsen heuristic + journey-mapping technique. No user testing was performed — the proposals are informed hypotheses that should be validated against real usage as the product grows.
