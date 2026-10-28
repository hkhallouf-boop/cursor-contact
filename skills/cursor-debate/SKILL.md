---
name: cursor-debate
description: Debate a design, plan, diff or technical decision with a different model through Cursor's CLI (Grok at high effort by default; any Cursor model via --model/--effort) in a multi-round, read-only exchange that ends with what was agreed, who conceded what, and what's still contested. Use this whenever the user says "debate this with cursor/grok", "get a second opinion from grok", "challenge my plan", "argue it out with cursor", "have another model poke holes in this", "is this the right approach? ask grok", "/cursor-debate", or wants an adversarial check of an approach before committing to it. Not for having Cursor write code — that is cursor-delegate.
---

# Cursor debate

The point is a decision that survived real pushback from a different model. That only works if the disagreement is genuine: don't cave to Cursor to be agreeable, and don't defend your first position out of reflex. Update when the evidence says so, hold when it doesn't.

The helper script is `scripts/cursor_run.py` inside this skill's directory (the base directory shown when the skill loads; `<skill-dir>` below). In debate mode it runs Cursor in its read-only `ask` mode and compares git state before and after, so any file Cursor touches is caught.

## Arguments

| Arg | Default | Notes |
| --- | --- | --- |
| `--model` | `grok` | Alias (`grok`, `opus`, `sonnet`, `gpt`, `gemini`, ...), a family (`grok-4.6`), or an exact Cursor model id. An alias resolves to the newest matching family on the account (`grok` → `grok-4.7`). Debating a model from a different vendor than Claude gives the most independent view. |
| `--effort` | `high` | `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`, or `default`. Cursor bakes effort into the model id (`grok-4.7-high`); the script picks the matching variant and reports in `note` if it had to substitute. |
| `--rounds` | `3` | Maximum rounds. Stop earlier when the debate has converged. |
| everything else | — | The question, plan, or diff to debate. |

## 1. Pin down the question and take a position first

- State the question precisely, e.g. "Should order-import concurrency be capped with an in-process semaphore or a database row lock?" If it's fuzzy, ask the user what decision they're trying to make.
- Gather the evidence yourself: read the code, the diff (`git diff`), the plan.
- Write down your own position before contacting Cursor: the recommendation, the reasoning, the assumptions it rests on, and the strongest objection you can think of. If you ask Cursor first, you'll anchor on its answer and the debate collapses into one opinion.

Preflight once:

```bash
python3 <skill-dir>/scripts/cursor_run.py check --model <model> --effort <effort>
```

`auth_required` → ask the user to run `agent login` in their terminal and stop. `model_not_found` → show `available_models` and ask. Otherwise note the resolved `model` and any `note` for the verdict header.

## 2. Opening brief (round 1)

Write it to a file in the scratchpad (or `$TMPDIR`). Cursor has none of this conversation and none of Claude's skills, so include the context it needs.

```markdown
# Debate: <the question>

You are the opposing reviewer in a structured technical debate. I hold the position below. Find where it is wrong, weak or incomplete, and say plainly where it is right. Don't invent disagreement and don't defer to me.

This is read-only: do not modify, create or delete files. Reading and searching the repository is encouraged — ground your arguments in the actual code.

## Context
<the system, relevant files with paths, constraints, what's been ruled out, project rules that bear on it>

## My position
<recommendation and reasoning>

## Points I'm least sure about
1. ...
2. ...

## What I want from you
For each numbered point: AGREE, DISAGREE or PARTIAL, with reasoning grounded in the code (cite path:line). Then raise anything important I missed. Then give your own recommendation if it differs.

End with:
## Summary
- Agree:
- Disagree:
- New issues:
- Your recommendation:
```

Dispatch:

```bash
python3 <skill-dir>/scripts/cursor_run.py run --mode debate \
  --model <model> --effort <effort> --prompt-file <round1.md>
```

Run it with the Bash tool's `run_in_background: true` and wait for the completion notification; don't poll. At high effort an opening round on real code can take 5–10+ minutes (the script allows 20 by default), which is past the foreground Bash limit. Tell the user in one line that round 1 is out. Note `chat_id` from the JSON: every later round resumes that same chat, so Cursor keeps its own reasoning from earlier rounds.

## 3. Rounds

After each reply:

1. **Verify Cursor's claims against the code.** Models cite lines that don't say what they claim. A claim that doesn't check out is a rebuttal point, with the real line quoted.
2. **Concede explicitly** where Cursor is right, and update your position. Say what changed your mind.
3. **Rebut with evidence** where it's wrong.
4. **Ask** about anything vague.

Next round's brief holds only what's new: your concessions, your rebuttal per point, open questions, and a request to answer per point and end with the same Summary block. Then:

```bash
python3 <skill-dir>/scripts/cursor_run.py run --mode debate \
  --model <model> --effort <effort> --resume <chat_id> --prompt-file <roundN.md>
```

Stop when there are no open disagreements, when both sides repeat themselves with no new evidence (that's a genuine tradeoff: record both positions), or at the round limit. Don't run extra rounds to "win".

If any run returns `git.readonly_violation: true`, stop the debate. Show the user `git.files_changed` and the diff, and let them decide whether to revert. Don't revert on your own: some of those files may hold their own work.

## 4. Verdict to the user

```markdown
## Debate: <question>
<model> · effort <effort> · <n> rounds

**Outcome:** <one or two sentences: the recommended decision>

**Agreed:**
- ...

**I conceded:** <what Cursor convinced me of, and why>
**Cursor conceded:** <what it dropped, and why>

**Still contested:**
- <point>: my view … / Cursor's view … / what would settle it (a test, a measurement, a product call for the user)

**New issues raised:** <things neither side started with>

**Recommendation:** <what to do now, and how it differs from my opening position>
```

Keep it honest: if Cursor's arguments were weak, say the debate mostly confirmed the original position; if it changed the plan, say that clearly. Mention `chat_id` so the user can continue the debate themselves in Cursor.
