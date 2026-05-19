# Codex Workspace Rules

This project was prepared by Claude Code/ClaudeKit and is now also operated through Codex.

## Startup Handoff

At the start of every Codex session in this workspace, read these files before planning or implementation:

1. `AGENTS.md` (this file)
2. `CLAUDE.md`
3. `README.md`
4. `docs/codex-memory.md`
5. `docs/session-sync.md`
6. `plans/260519-2134-meeting-transcript-pipeline/plan.md`
7. `plans/reports/brainstorm-260519-2103-meeting-transcript-pipeline.md`
8. Any phase file under `plans/260519-2134-meeting-transcript-pipeline/` relevant to the task

If the user asks to continue previous work, treat `docs/codex-memory.md`, `docs/session-sync.md`, and `plans/` as the primary context source.

## ClaudeKit Compatibility

ClaudeKit skills have been synced into `~/.codex/skills` so Codex can discover the `ck:*` skills by name. Project-level Claude rules are kept in `.claude/rules/`.

Codex does not run Claude Code slash commands directly. Map `/ck:*` command intent to the matching `ck:*` skill when available, then follow the skill workflow using Codex tools.

## Local Constraints

- This directory is now initialized as a Git repo on `main`.
- Target public repo from Claude handoff: `https://github.com/sonpython/google-meet-transcript-bot.git`. It existed but had no remote refs when checked on 2026-05-19, so there was no upstream code to pull.
- Follow `CLAUDE.md` and `.claude/rules/development-rules.md` where they do not conflict with Codex system/developer instructions.
- Keep generated status and memory docs in `docs/` unless the user asks for private local-only notes.
