#!/usr/bin/env python3
"""Run Cursor's CLI agent (cursor-agent) headless on behalf of a Claude skill.

Shared by the cursor-delegate and cursor-debate skills (each ships an identical copy,
so either skill works when installed on its own). macOS and Linux; needs Python 3.9+.

Subcommands
  check   Preflight: binary, auth, model resolution, git state. Makes no model call.
  run     Dispatch one prompt. --mode delegate may write files; --mode debate is read-only.

Always prints exactly one JSON object on stdout (exit 0 when status == "ok", else 1).
The prompt, raw event stream and the full result are kept in the run directory.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

DEFAULT_MODEL = "grok"
DEFAULT_EFFORT = "high"
DEFAULT_TIMEOUT = {"delegate": 1800, "debate": 1200}
# Cursor sometimes keeps the process alive after emitting its final result.
POST_RESULT_GRACE_SEC = 15
FINAL_MESSAGE_STDOUT_CAP = 20000
RUNS_ROOT = Path(
    os.environ.get("CURSOR_SKILL_RUNS_DIR") or Path(tempfile.gettempdir()) / "cursor-skill-runs"
)

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
MODEL_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._\-]*$")
CHAT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:\-]*$")
AUTH_HINTS = ("authentication required", "not logged in", "agent login")


# ---------------------------------------------------------------- helpers

def find_bin():
    override = os.environ.get("CURSOR_AGENT_BIN")
    if override:
        return override
    for name in ("cursor-agent", "agent"):
        path = shutil.which(name)
        if path:
            return path
    return None


def sh(cmd, cwd=None, timeout=60):
    try:
        res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return res.returncode, res.stdout, res.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "timed out"
    except FileNotFoundError as err:
        return 127, "", str(err)


def emit(result, run_dir=None):
    if run_dir is not None:
        (run_dir / "result.json").write_text(json.dumps(result, indent=2))
    out = dict(result)
    msg = out.get("final_message")
    if isinstance(msg, str) and len(msg) > FINAL_MESSAGE_STDOUT_CAP:
        out["final_message"] = msg[:FINAL_MESSAGE_STDOUT_CAP]
        out["final_message_truncated"] = True
    print(json.dumps(out, indent=2))
    return 0 if result.get("status") == "ok" else 1


# ---------------------------------------------------------------- models

def list_models(binp):
    """Return (ids, raw_text, problem). ids is None when auth is missing."""
    code, out, err = sh([binp, "--list-models"], timeout=60)
    text = ANSI_RE.sub("", f"{out}\n{err}")
    if code != 0:
        if any(h in text.lower() for h in AUTH_HINTS):
            return None, text, "auth_required"
        return [], text, "list_failed"
    ids = []
    for line in ANSI_RE.sub("", out).splitlines():
        stripped = line.strip().lstrip("-*•").strip()
        if not stripped:
            continue
        token = stripped.split()[0].rstrip(",:")
        if MODEL_ID_RE.match(token) and token not in ids:
            ids.append(token)
    return ids, text, None


# Cursor encodes effort (and a "fast" serving tier) as id suffixes:
# grok-4.7-high, grok-4.7-high-fast, gpt-5.5-extra-high, composer-2.5 (no levels).
EFFORT_SUFFIXES = ["extra-high", "minimal", "medium", "xhigh", "none", "high", "low", "max"]
EFFORT_ORDER = ["none", "minimal", "low", "medium", "high", "xhigh", "max"]
EFFORT_SYNONYMS = {"extra-high": "xhigh", "extra_high": "xhigh", "extrahigh": "xhigh", "med": "medium"}
VERSION_RE = re.compile(r"\d+(?:[.\-]\d+)*")


def split_id(mid):
    """'grok-4.7-high-fast' -> ('grok-4.7', 'high', True)."""
    rest, fast = (mid[:-5], True) if mid.endswith("-fast") else (mid, False)
    for suffix in EFFORT_SUFFIXES:
        if rest.endswith(f"-{suffix}"):
            return rest[: -len(suffix) - 1], EFFORT_SYNONYMS.get(suffix, suffix), fast
    return rest, None, fast


def version_key(family):
    match = VERSION_RE.search(family)
    nums = [int(n) for n in re.split(r"[.\-]", match.group())] if match else []
    nums = (nums + [0, 0, 0, 0])[:4]  # so 5 compares as 5.0 against 5.5
    # Newest version first; among equals, the plainer (shorter) family name.
    return tuple(-n for n in nums), len(family), family


def pick_variant(family, variants, effort):
    """Choose the id in a family for the wanted effort. Returns (id, effort_used, note)."""
    slow = [v for v in variants if not v[2]] or variants
    by_effort = {v[1]: v[0] for v in slow}
    if not effort or effort == "default":
        for level in (None, "medium", "high"):
            if level in by_effort:
                return by_effort[level], level, None
        return slow[0][0], slow[0][1], None
    if effort in by_effort:
        return by_effort[effort], effort, None
    levels = sorted((e for e in by_effort if e), key=EFFORT_ORDER.index)
    if not levels:
        return by_effort.get(None, slow[0][0]), None, f"{family} has no effort levels; ran its default"
    if None in by_effort:
        return by_effort[None], None, f"{family} has no '{effort}' level (has {', '.join(levels)}); ran its default"
    want = EFFORT_ORDER.index(effort) if effort in EFFORT_ORDER else EFFORT_ORDER.index("high")
    nearest = min(levels, key=lambda e: abs(EFFORT_ORDER.index(e) - want))
    return by_effort[nearest], nearest, f"{family} has no '{effort}' level; used nearest '{nearest}'"


def resolve_model(requested, ids, effort):
    """Map an alias like 'grok' plus an effort onto a real Cursor model id.

    Returns a dict with model (None if nothing matches), effort_used, families, note, verified.
    """
    effort = EFFORT_SYNONYMS.get((effort or "").lower(), (effort or "").lower()) or None
    if effort == "default":
        effort = None  # the family's own default variant; "none" is a real GPT level
    if "[" in requested or not ids:
        # Explicit parameterised id, or no list to check against: pass through.
        return {"model": requested, "effort_used": None, "families": [], "verified": False,
                "note": "model id passed through unverified; effort not applied"}
    lower = requested.lower()
    for mid in ids:
        if mid.lower() == lower and split_id(mid)[1] is not None:
            # Already a full id with an effort level baked in.
            note = None if not effort or split_id(mid)[1] == effort else (
                f"'{mid}' already fixes effort to {split_id(mid)[1]}; --effort ignored")
            return {"model": mid, "effort_used": split_id(mid)[1], "families": [], "verified": True, "note": note}

    families = {}
    for mid in ids:
        family, level, fast = split_id(mid)
        families.setdefault(family, []).append((mid, level, fast))
    if lower in families:
        chosen = [lower]
    else:
        chosen = sorted((f for f in families if lower in f), key=version_key)
    if not chosen:
        if lower in (m.lower() for m in ids):
            return {"model": requested, "effort_used": None, "families": [], "verified": True,
                    "note": "exact id; it has no effort levels"}
        return {"model": None, "effort_used": None, "families": [], "verified": True, "note": None}
    family = chosen[0]
    mid, used, note = pick_variant(family, families[family], effort)
    return {"model": mid, "effort_used": used, "families": chosen, "verified": True, "note": note}


# ---------------------------------------------------------------- git

def git_root(cwd):
    code, out, _ = sh(["git", "rev-parse", "--show-toplevel"], cwd=cwd)
    return out.strip() if code == 0 else None


def file_hash(root, rel):
    path = Path(root) / rel
    if not path.exists():
        return "deleted"
    if path.is_dir():
        return "dir"
    digest = hashlib.sha1()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot(root):
    if not root:
        return None
    code, out, _ = sh(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"], cwd=root
    )
    if code != 0:
        return None
    files = {}
    parts = out.split("\0")
    i = 0
    while i < len(parts):
        entry = parts[i]
        i += 1
        if not entry:
            continue
        status, rel = entry[:2], entry[3:]
        if status[0] in "RC":
            i += 1  # -z puts the rename/copy source path in the next field
        files[rel] = [status, file_hash(root, rel)]
    head = sh(["git", "rev-parse", "HEAD"], cwd=root)[1].strip()
    return {"head": head, "files": files}


def changes_between(root, before, after):
    if before is None or after is None:
        return [], False
    changed = set()
    for rel, (_, digest) in after["files"].items():
        prev = before["files"].get(rel)
        if prev is None or prev[1] != digest:
            changed.add(rel)
    for rel in before["files"]:
        if rel not in after["files"]:
            changed.add(rel)  # was dirty, now matches HEAD again
    head_moved = bool(before["head"]) and before["head"] != after["head"]
    if head_moved:
        out = sh(["git", "diff", "--name-only", before["head"], after["head"]], cwd=root)[1]
        changed.update(line for line in out.splitlines() if line)
    return sorted(changed), head_moved


# ---------------------------------------------------------------- run

def text_of(message):
    if isinstance(message, str):
        return message
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )
    return ""


def kill_group(proc):
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


def feed_stdin(proc, prompt):
    try:
        proc.stdin.write(prompt)
        proc.stdin.close()
    except (BrokenPipeError, OSError):
        pass  # cursor-agent exited early (bad model, auth); its exit code reports it


def run_agent(binp, extra_args, prompt, cwd, timeout, run_dir):
    # The prompt goes over stdin, not argv: Linux caps a single argument at 128 KB,
    # which a brief with a pasted diff can exceed.
    cmd = [binp, "-p", "--output-format", "stream-json", "--trust", *extra_args]
    events_path = run_dir / "events.ndjson"
    stderr_path = run_dir / "stderr.log"
    state = {
        "chat_id": None,
        "result_text": None,
        "assistant_text": None,
        "is_error": False,
        "tool_calls": {},
        "result_at": None,
        "timed_out": False,
        "killed_after_result": False,
        "event_count": 0,
    }
    started = time.time()
    with stderr_path.open("w") as err_fh:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=err_fh,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        # Written from a thread so a large prompt can't deadlock against stdout.
        threading.Thread(target=feed_stdin, args=(proc, prompt), daemon=True).start()
        done = threading.Event()

        def watchdog():
            while not done.wait(1):
                now = time.time()
                if now - started > timeout:
                    state["timed_out"] = True
                    kill_group(proc)
                    return
                if state["result_at"] and now - state["result_at"] > POST_RESULT_GRACE_SEC:
                    state["killed_after_result"] = True
                    kill_group(proc)
                    return

        threading.Thread(target=watchdog, daemon=True).start()
        with events_path.open("w") as ev_fh:
            for line in proc.stdout:
                ev_fh.write(line)
                ev_fh.flush()
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(ev, dict):
                    continue
                state["event_count"] += 1
                for key in ("session_id", "chat_id", "chatId", "sessionId"):
                    if isinstance(ev.get(key), str) and ev[key]:
                        state["chat_id"] = ev[key]
                        break
                etype = ev.get("type")
                if etype == "assistant":
                    text = text_of(ev.get("message"))
                    if text:
                        state["assistant_text"] = text
                elif etype == "tool_call" and ev.get("subtype") in (None, "started"):
                    call = ev.get("tool_call")
                    name = next(iter(call), "tool") if isinstance(call, dict) else "tool"
                    state["tool_calls"][name] = state["tool_calls"].get(name, 0) + 1
                elif etype == "result":
                    if isinstance(ev.get("result"), str):
                        state["result_text"] = ev["result"]
                    subtype = ev.get("subtype")
                    if ev.get("is_error") or (subtype and subtype != "success"):
                        state["is_error"] = True
                    state["result_at"] = state["result_at"] or time.time()
        proc.wait()
        done.set()
    state["exit_code"] = proc.returncode
    state["duration_sec"] = round(time.time() - started, 1)
    state["stderr_tail"] = stderr_path.read_text(errors="replace")[-2000:]
    return state


# ---------------------------------------------------------------- commands

def base_result(args):
    return {
        "status": "ok",
        "mode": getattr(args, "mode", None),
        "model_requested": args.model,
        "effort_requested": args.effort,
    }


def preflight(args, result):
    """Resolve binary, auth and model. Returns (binp, resolved) or (None, None) on failure."""
    binp = find_bin()
    if not binp:
        result.update(status="no_binary", hint="Install: curl https://cursor.com/install -fsS | bash")
        return None, None
    result["binary"] = binp
    ids, raw, problem = list_models(binp)
    if problem == "auth_required":
        result.update(status="auth_required", hint="Ask the user to run `agent login` in a terminal.")
        return None, None
    resolved = resolve_model(args.model, ids, args.effort)
    result["model_families"] = resolved["families"]
    result["model_verified"] = resolved["verified"]
    if resolved["model"] is None:
        result.update(status="model_not_found", available_models=ids)
        return None, None
    result["model"] = resolved["model"]
    result["effort_used"] = resolved["effort_used"]
    if resolved["note"]:
        result["note"] = resolved["note"]
    if problem == "list_failed":
        result["warning"] = "could not list models; model id passed through unverified"
    return binp, resolved


def cmd_check(args):
    result = base_result(args)
    cwd = os.path.abspath(args.workspace)
    binp, _ = preflight(args, result)
    if binp:
        result["version"] = sh([binp, "--version"])[1].strip()
    root = git_root(cwd)
    snap = snapshot(root)
    result["git"] = {
        "root": root,
        "dirty_files": sorted(snap["files"]) if snap else [],
    }
    return emit(result)


def cmd_run(args):
    result = base_result(args)
    cwd = os.path.abspath(args.workspace)
    prompt = Path(args.prompt_file).read_text()
    if not prompt.strip():
        result.update(status="error", error="prompt file is empty")
        return emit(result)
    if args.resume and not CHAT_ID_RE.match(args.resume):
        result.update(status="error", error=f"invalid chat id: {args.resume!r}")
        return emit(result)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = RUNS_ROOT / f"{stamp}-{args.mode}-{os.getpid()}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "prompt.md").write_text(prompt)
    result["run_dir"] = str(run_dir)

    binp, _ = preflight(args, result)
    if not binp:
        return emit(result, run_dir)

    root = git_root(cwd)
    before = snapshot(root)

    common = []
    if args.mode == "delegate":
        common.append("--force")
    else:
        # Cursor's own read-only mode; the git comparison below double-checks it.
        common += ["--mode", "ask"]
    if args.resume:
        # Always pass an explicit id: a bare --resume reopens Cursor's most recent
        # chat, which may belong to unrelated work.
        common.append(f"--resume={args.resume}")
    timeout = args.timeout or DEFAULT_TIMEOUT[args.mode]

    state = run_agent(binp, ["--model", result["model"], *common], prompt, cwd, timeout, run_dir)

    after = snapshot(root)
    changed, head_moved = changes_between(root, before, after)

    if state["timed_out"]:
        status = "timeout"
    elif state["is_error"] or (state["exit_code"] not in (0, None) and not state["killed_after_result"]):
        status = "error"
    elif not (state["result_text"] or state["assistant_text"]):
        status = "error"
    else:
        status = "ok"

    result.update(
        status=status,
        chat_id=state["chat_id"],
        final_message=state["result_text"] or state["assistant_text"] or "",
        exit_code=state["exit_code"],
        duration_sec=state["duration_sec"],
        tool_calls=state["tool_calls"],
        git={
            "root": root,
            "dirty_before": sorted(before["files"]) if before else [],
            "files_changed": changed,
            "head_moved": head_moved,
            "readonly_violation": args.mode == "debate" and bool(changed or head_moved),
        },
    )
    if status != "ok":
        result["stderr_tail"] = state["stderr_tail"]
    return emit(result, run_dir)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    def shared(p):
        p.add_argument("--model", default=DEFAULT_MODEL, help="alias (grok, composer, sonnet...) or exact Cursor model id")
        p.add_argument("--effort", default=DEFAULT_EFFORT, help="none|minimal|low|medium|high|xhigh|max, or default for the family default")
        p.add_argument("--workspace", default=".", help="directory Cursor works in (default: cwd)")

    check = sub.add_parser("check", help="preflight only")
    shared(check)

    run = sub.add_parser("run", help="dispatch one prompt")
    shared(run)
    run.add_argument("--mode", choices=["delegate", "debate"], required=True)
    run.add_argument("--prompt-file", required=True)
    run.add_argument("--resume", help="Cursor chat id to continue (from a previous run's chat_id)")
    run.add_argument("--timeout", type=int, help="seconds (default 1800 delegate, 1200 debate)")

    args = parser.parse_args()
    return cmd_check(args) if args.command == "check" else cmd_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
