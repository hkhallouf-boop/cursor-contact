# cursor-contact

Claude Code skills that put Cursor's agent on your team. Claude plans and reviews; Cursor writes the code, or argues the other side of a design. You choose the model and the effort, and nothing lands until Claude has checked it.

| Skill | What it does |
| --- | --- |
| **`cursor-delegate`** | Hands a coding task to Cursor's CLI agent with a self-contained brief, then reviews the real diff, runs your tests, sends targeted fixes back to the same Cursor chat if needed, and reports. It never commits. |
| **`cursor-debate`** | Stress-tests a design, plan or diff against a different model. Claude states its position first, then debates Cursor for up to 3 read-only rounds in one chat, checks every code citation, and ends with what was agreed, who conceded what, and what's still contested. |

Both default to **Grok at high effort** (`grok` → `grok-4.7-high` today), and both take `--model` and `--effort` for anything else your Cursor plan offers: Opus, Sonnet, GPT, Gemini, Composer and more.

## Why

- **Use the right model for the job.** Claude stays in charge of planning and review; the typing or the counter-argument comes from whichever model you pick.
- **A real second opinion.** Debating a model from another vendor catches blind spots a self-review won't. The skill tells Claude not to cave to agree and not to dig in by reflex.
- **Trust the diff, not the summary.** The helper script snapshots git before and after every run, so Claude reviews the files that actually changed, not the ones Cursor says it changed.

## Requirements

- [Claude Code](https://claude.com/claude-code)
- The Cursor CLI, logged in:
  ```bash
  curl https://cursor.com/install -fsS | bash
  ```
  ```bash
  agent login
  ```
- A Cursor plan that includes the models you want to use. Check what your account has with `cursor-agent --list-models`.
- Python 3.9+ and git, on macOS or Linux. The helper script uses only the standard library.

## Install

**As a Claude Code plugin (recommended).** In Claude Code:

```
/plugin marketplace add hkhallouf-boop/cursor-contact
/plugin install cursor-contact@cursor-contact
```

Then restart Claude Code, or run `/reload-plugins`.

**With [skills.sh](https://skills.sh):**

```bash
npx skills add hkhallouf-boop/cursor-contact
```

**By hand.** Clone the repo and link (or copy) the skills into your personal skills folder:

```bash
git clone https://github.com/hkhallouf-boop/cursor-contact ~/cursor-contact
```

```bash
ln -s ~/cursor-contact/skills/cursor-delegate ~/cursor-contact/skills/cursor-debate ~/.claude/skills/
```

Each skill is self-contained (it ships its own copy of the helper script), so you can install just one.

## Use

Ask in plain words, or call the skill directly. When installed as a plugin, the slash commands are namespaced: `/cursor-contact:cursor-delegate` and `/cursor-contact:cursor-debate`.

**Delegate**

```
delegate this to cursor: add an apply_coupon(total, percent) helper to pricing.py, clamp percent to 0-100, with tests
```

```
/cursor-delegate --model opus --effort xhigh refactor the retry logic in src/billing/client.py to use exponential backoff
```

Claude checks that Cursor is installed and logged in, warns you if you have uncommitted changes, writes Cursor a brief (goal, files, requirements, your project rules, how to verify, guardrails), runs it, reviews the diff, runs your tests, and reports. It leaves the commit to you.

**Debate**

```
debate with grok whether caching the price list in Redis is the right fix for the slow checkout, before I build it
```

```
/cursor-debate --model gpt --effort high --rounds 2 is a DB row lock or a queue the better way to stop double imports here?
```

You get a verdict like this:

```
## Debate: Redis cache for the price list?
grok-4.7-high · effort high · 2 rounds

**Outcome:** ...
**Agreed:** ...
**I conceded:** ...      **Cursor conceded:** ...
**Still contested:** ... (and what would settle it)
**Recommendation:** ...
```

### Options

| Option | Default | Meaning |
| --- | --- | --- |
| `--model` | `grok` | An alias (`grok`, `opus`, `sonnet`, `gpt`, `codex`, `gemini`, `composer`, ...), a model family (`grok-4.6`), or an exact Cursor model id (`claude-opus-5-5-max`). |
| `--effort` | `high` | `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`, or `default`. |
| `--rounds` | `3` | Debate only: the most rounds to run. It stops early once the two sides converge. |
| `--timeout` | 1800 s for delegate, 1200 s per debate round | Raise it for big tasks. |

**How models and effort are matched.** Cursor puts the effort level in the model id (`grok-4.7-high`, `grok-4.7-xhigh`), so the script reads your account's model list:

1. It picks the **newest family** that matches the alias: `grok` → `grok-4.7`, `sonnet` → `claude-sonnet-5-5`.
2. It picks the **variant for your effort** in that family.
3. If that level doesn't exist, it uses the nearest one or the family's default, and Claude tells you. For example, `composer` has no effort levels.

It never picks the `-fast` serving tier unless you name it.

## How it works

```
you ──► Claude ──brief──► scripts/cursor_run.py ──► cursor-agent -p (stream-json)
            ▲                     │  git snapshot before / after
            │                     ▼
            └──── review ◄── JSON: model, chat_id, final message, files changed
```

`scripts/cursor_run.py` is a small standard-library wrapper around `cursor-agent`. It:

- resolves the model and effort;
- runs Cursor headless, with the prompt sent on stdin;
- stops the run on a timeout, or if Cursor hangs after its final answer;
- compares git state before and after the run;
- prints one JSON result for Claude.

Each run's prompt, raw event log and result are saved under `$TMPDIR/cursor-skill-runs/`. Set `CURSOR_SKILL_RUNS_DIR` to put them somewhere else, and `CURSOR_AGENT_BIN` to point at a non-standard `cursor-agent`.

## Safety

- **Delegation writes to your working tree.** It runs `cursor-agent --force`, so Cursor applies edits and runs shell commands without asking for each one. The brief tells it not to commit, push, switch branches or run destructive commands, and Claude reviews everything afterwards. Even so, delegate on a clean tree or a branch you don't mind resetting. Claude warns you first when the tree has uncommitted changes.
- **Debates are read-only, and it's enforced.** Cursor runs in its read-only `ask` mode, and the git comparison flags any file that changes anyway. In that case Claude stops the debate and shows you the diff instead of reverting it.
- **Follow-ups go to the right chat.** They always resume an explicit chat id, never Cursor's "most recent chat", which could belong to unrelated work.
- **No secrets are handled.** The skills use your existing `agent login` session and never ask for or store credentials.

Claude Code may ask your permission the first time it runs the helper script. If you use auto mode, note that running `cursor-agent --force` directly can be blocked by the permission checker; the skills go through the script.

## Troubleshooting

| Script status | What to do |
| --- | --- |
| `auth_required` | Run `agent login` in a terminal. |
| `no_binary` | Install the Cursor CLI, or set `CURSOR_AGENT_BIN`. |
| `model_not_found` | Pick a model from the `available_models` list in the output, or run `cursor-agent --list-models`. |
| `timeout` | Pass a larger `--timeout`. Check `git status`, since a delegated run may have left partial edits. |
| `error` | Read `stderr_tail` in the output. The full log is in the run's `run_dir`. |

## Development

```bash
python3 -m unittest discover -s tests -v
```

The unit tests cover model and effort matching (against a real Cursor model list) and change detection. They need no Cursor account. Both skills ship the same `cursor_run.py`; edit the one in `skills/cursor-delegate/scripts/` and copy it over, and a test fails if the copies drift apart.

Each skill also has eval cases in `evals/` that run the real workflow on a small sample repo. They use Cursor credits. To run them with Claude Code:

```bash
claude plugin eval skills/cursor-delegate --scaffold --allow-tools Write,Edit,Bash
```

Issues and pull requests are welcome.

## Related

- [freema/cursor-plugin-cc](https://github.com/freema/cursor-plugin-cc): slash commands for delegating to Cursor from Claude Code.
- [amElnagdy/delegate-skills](https://github.com/amElnagdy/delegate-skills): delegation skills for many CLI coding agents.

## License

[MIT](LICENSE)
