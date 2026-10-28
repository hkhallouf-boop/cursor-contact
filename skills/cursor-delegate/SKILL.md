---
name: cursor-delegate
description: Delegate a coding task to Cursor's CLI agent (cursor-agent) — Grok at high effort by default, any Cursor model via --model/--effort — then review its diff and run the checks before anything lands. Use this whenever the user says "delegate to cursor", "have cursor/grok implement/write/fix/refactor X", "send this to cursor", "let grok do it", "offload this to cursor", "/cursor-delegate", or otherwise wants another agent (Cursor, Grok, Composer, GPT or Sonnet through Cursor) to write the code while Claude plans and reviews. Not for second opinions or arguing a design — that is cursor-debate.
---

# Cursor delegate

Claude plans and reviews; Cursor writes. You stay accountable for the result: Cursor's own summary is a claim, the diff is the evidence.

The helper script is `scripts/cursor_run.py` inside this skill's directory (the base directory shown when the skill loads; `<skill-dir>` below). It wraps `cursor-agent`, resolves model aliases, applies effort, and reports exactly which files changed by comparing git state before and after — so you never have to trust Cursor's own list.

## Arguments

Read these from the user's request (flags or plain words like "use sonnet, medium effort"):

| Arg | Default | Notes |
| --- | --- | --- |
| `--model` | `grok` | Alias (`grok`, `composer`, `sonnet`, `opus`, `gpt`, `codex`, `gemini`, ...), a family (`grok-4.6`), or an exact Cursor model id. An alias resolves to the newest matching family on the account (`grok` → `grok-4.7`). |
| `--effort` | `high` | `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`, or `default`. Cursor bakes effort into the model id (`grok-4.7-high`), so the script picks the family's variant for that level. If the family lacks it, it says so in `note` and runs the nearest level or the default. An exact id like `grok-4.7-xhigh` already fixes effort. |
| `--timeout` | `1800` s | Raise it for big tasks. |
| everything else | — | The task. |

If the task is vague (no clear outcome, no idea which area of the code), ask before dispatching. A vague brief burns a whole run and produces a diff you'll throw away.

## 1. Preflight

```bash
python3 <skill-dir>/scripts/cursor_run.py check --model <model> --effort <effort>
```

- `auth_required` → tell the user to run `agent login` in their own terminal, then stop. Never try to log in for them.
- `model_not_found` → show `available_models` and ask which one they meant.
- Mention the resolved `model` and any `note` (e.g. "composer-2.5 has no effort levels"). If `model_families` lists several, name the one picked so the user can ask for another.
- `git.dirty_files` not empty → Cursor will edit the same checkout, so its changes get tangled with the user's uncommitted work. Tell them which files are dirty and continue only if they're fine with it (or already said to go ahead). The script tracks pre-existing dirty files separately, so the review can still tell the two apart.

## 2. Write the brief

Cursor starts cold: it has none of this conversation and none of Claude's skills. It reads `AGENTS.md` / `.cursor/rules` on its own; don't count on it reading `CLAUDE.md`. Everything it needs has to be in the brief. Write it to a file in the scratchpad (or `$TMPDIR`), not into the repo.

```markdown
# Task: <one line>

## Goal
<the outcome, and why it matters in one or two sentences>

## Context
<what exists today; relevant files with paths and the functions/classes involved; anything already ruled out>

## Requirements
1. <concrete, checkable>
2. ...

## Files
- Touch: <paths>
- Do not touch: <paths or areas, if there's a risk>

## Project rules
<only the rules that apply to this change, pasted from CLAUDE.md, AGENTS.md or the team's conventions: naming, layering, error handling, test style, schema-change rules...>

## How to verify
<exact commands, e.g. `pytest tests/test_orders.py -k refund`>

## Guardrails
- Do not commit, push, create branches or stash.
- Do not modify lockfiles or unrelated files; no drive-by refactors.
- No destructive commands (rm -rf, git reset/checkout/clean, dropping data).
- If a requirement is ambiguous or you're blocked, stop and say so in your final message instead of guessing.

## Final message
List the files you changed, what you did for each requirement, the commands you ran with their results, and anything left undone.
```

Specific file paths and checkable requirements are what move Cursor's output quality the most; long prose doesn't. If the project's rules live in another skill or doc, load it yourself and paste the relevant parts.

## 3. Dispatch

```bash
python3 <skill-dir>/scripts/cursor_run.py run --mode delegate \
  --model <model> --effort <effort> --prompt-file <brief.md> [--timeout <sec>]
```

Run it with the Bash tool's `run_in_background: true`: delegated runs take minutes and can outlast the foreground limit. You get notified when it exits; don't poll. Tell the user in one line what went out (model, effort, the task).

The JSON it prints:

- `status`: `ok` | `error` | `timeout` | `auth_required` | `model_not_found` | `no_binary`
- `model`, `effort_used`, `note`: what actually ran (`note` explains a missing or substituted effort level)
- `chat_id`: the Cursor chat, needed to send follow-ups
- `final_message`: Cursor's last message (full copy in `run_dir/result.json` if truncated)
- `git.files_changed`: files changed during the run (real, from git); `git.dirty_before`: files that were already dirty; `git.head_moved`: Cursor made a commit
- `tool_calls`, `duration_sec`, `run_dir` (prompt, raw event log, stderr)

## 4. Review — the part that matters

1. Read the diff of everything in `git.files_changed` (`git diff -- <files>`, and read new untracked files in full). For files that were already dirty, separate Cursor's edits from the user's using your knowledge of the earlier state.
2. Check each requirement in the brief against the code, not against `final_message`.
3. Run the verify commands yourself. Cursor saying "tests pass" is not a test run.
4. Look for the usual failure modes: scope creep outside the file list, deleted or weakened tests, hard-coded values, stubbed `TODO`s, swallowed errors, project-rule violations.
5. If `git.head_moved` is true, Cursor committed despite the guardrail — tell the user and leave the commit alone unless they decide otherwise.

Then decide:

- **Good** → report.
- **Small issues** (an import, a typo, one-line fix) → fix them yourself; a round trip costs more than the fix.
- **Real issues** → send numbered, specific fixes to the same chat:
  ```bash
  python3 <skill-dir>/scripts/cursor_run.py run --mode delegate \
    --model <model> --effort <effort> --resume <chat_id> --prompt-file <fixes.md>
  ```
  Always pass the explicit `chat_id`. Allow at most two fix rounds; if it still isn't right, finish it yourself or hand the remaining issues to the user.

## 5. Report

Keep it short:

- Model and effort that ran (the resolved id, plus any `note`).
- What changed: files, one line each.
- Review result per requirement, plus anything you fixed yourself.
- Verification: commands run and outcome; paste failures.
- `chat_id`, in case the user wants to continue the chat.

Don't commit; the user decides when to commit.

## When things go wrong

- `timeout` → Cursor may have left partial edits. Show `git.files_changed`, and ask whether to keep, finish or discard them. Don't discard on your own.
- `error` → show `stderr_tail`; common causes are auth expiry (`agent login`), an unknown model, or no credits.
- Empty `files_changed` with a "done" message → Cursor did nothing (or wrote outside the repo). Say so plainly.
