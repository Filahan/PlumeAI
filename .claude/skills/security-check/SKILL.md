---
name: security-check
description: Run before any git commit in this repo. Blocks commits that contain secrets, .env files, or known dangerous patterns. Auto-invoke whenever the user asks to commit or you intend to run `git commit`.
---

# Security check before commit

Before invoking ANY `git commit` (including `git commit -m "..."`, `git commit --amend`,
or any variant), you MUST run the project's pre-commit hook as a dry-run.

## Procedure

1. From the repo root, run:

   ```bash
   bash .githooks/pre-commit
   ```

2. If the script exits with a **non-zero** status:
   - **DO NOT** run `git commit`.
   - Surface the script's stderr output to the user verbatim.
   - Explain which finding triggered the block (e.g. "OpenAI API key in `apps/web/foo.ts:42`").
   - Suggest concrete next steps:
     - For real secrets: move to env vars / encrypted storage, unstage the file with `git restore --staged <file>`.
     - For false positives: add `# pragma: allowlist secret` on the same line.

3. If the script exits with **zero**, proceed with the commit normally.

## Why this skill exists

The git hook at `.githooks/pre-commit` is the source of truth. But it only runs
automatically if the user has run `git config core.hooksPath .githooks` in their
clone (one-time setup). This skill enforces the same check from the agent side
so it works even on a fresh clone where the hook isn't wired yet.

## What gets blocked

- `.env`, `.env.local`, `.env.production`, etc. (but `.env.example` is allowed)
- Files ending in `.pem`, `.key`, `.p12`, `.pfx`, `.jks`, `.keystore`
- Staged diff containing patterns for: OpenAI / Anthropic / Google OAuth / Google API / AWS / Discord bot / PEM private keys / Slack / GitHub PAT / Stripe live keys

## Reference

Full hook script: `.githooks/pre-commit`
Setup instructions: `docs/security.md`
