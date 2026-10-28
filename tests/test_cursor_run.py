"""Unit tests for skills/*/scripts/cursor_run.py. No Cursor account or network needed.

Run: python3 -m unittest discover -s tests -v
"""
import filecmp
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = [ROOT / "skills" / name / "scripts" / "cursor_run.py" for name in ("cursor-delegate", "cursor-debate")]

spec = importlib.util.spec_from_file_location("cursor_run", SCRIPTS[0])
cr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cr)

# A slice of a real `cursor-agent --list-models` listing (October 2026), in Cursor's own order.
MODELS = """\
Available models

auto - Auto (default)
gpt-5.3-codex-low - Codex 5.3 Low
gpt-5.3-codex - Codex 5.3
gpt-5.3-codex-high - Codex 5.3 High
composer-2.5 - Composer 2.5
cursor-grok-4.5-high - Grok 4.5
cursor-grok-4.5-high-fast - Grok 4.5 Fast
grok-4.7-low - Grok 4.7  Low
grok-4.7-medium - Grok 4.7  Medium
grok-4.7-high - Grok 4.7  High
grok-4.7-high-fast - Grok 4.7  High Fast​​
grok-4.7-xhigh - Grok 4.7  Extra High
cursor-grok-4.6-low - Grok 4.6 Low
cursor-grok-4.6-high - Grok 4.6
composer-2.5-fast - Composer 2.5 Fast
claude-opus-5-5-medium - Claude Opus 5.5 1M
claude-opus-5-5-high - Claude Opus 5.5 1M High
claude-opus-5-5-max - Claude Opus 5.5 1M Max
gpt-5.5-none - GPT-5.5 1M None
gpt-5.5-medium - GPT-5.5 1M
gpt-5.5-high - GPT-5.5 1M High
gpt-5.5-extra-high - GPT-5.5 1M Extra High
claude-sonnet-5-5-high - Claude Sonnet 5.5  High
claude-sonnet-5-high - Claude Sonnet 5 1M
gpt-5-mini - GPT-5 Mini
"""


def parse_ids(text):
    ids = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        token = stripped.split()[0]
        if cr.MODEL_ID_RE.match(token) and token not in ids:
            ids.append(token)
    return ids


IDS = parse_ids(MODELS)


class ScriptCopies(unittest.TestCase):
    def test_both_skills_ship_the_same_script(self):
        self.assertTrue(filecmp.cmp(*SCRIPTS, shallow=False), "sync skills/*/scripts/cursor_run.py")


class ListParsing(unittest.TestCase):
    def test_header_is_skipped_and_ids_kept_in_order(self):
        self.assertEqual(IDS[0], "auto")
        self.assertNotIn("Available", IDS)
        self.assertIn("grok-4.7-high-fast", IDS)


class SplitId(unittest.TestCase):
    def test_suffixes(self):
        self.assertEqual(cr.split_id("grok-4.7-high-fast"), ("grok-4.7", "high", True))
        self.assertEqual(cr.split_id("gpt-5.5-extra-high"), ("gpt-5.5", "xhigh", False))
        self.assertEqual(cr.split_id("composer-2.5"), ("composer-2.5", None, False))
        self.assertEqual(cr.split_id("claude-opus-5-5-max"), ("claude-opus-5-5", "max", False))


class ResolveModel(unittest.TestCase):
    def resolve(self, model, effort="high"):
        return cr.resolve_model(model, IDS, effort)

    def test_default_grok_high_is_newest_family(self):
        r = self.resolve("grok")
        self.assertEqual(r["model"], "grok-4.7-high")
        self.assertEqual(r["effort_used"], "high")
        self.assertIsNone(r["note"])

    def test_versions_compare_numerically(self):
        self.assertEqual(self.resolve("sonnet")["model"], "claude-sonnet-5-5-high")
        self.assertEqual(self.resolve("gpt")["model"], "gpt-5.5-high")

    def test_missing_level_uses_nearest(self):
        r = self.resolve("grok", "max")
        self.assertEqual(r["model"], "grok-4.7-xhigh")
        self.assertIn("nearest", r["note"])

    def test_missing_level_prefers_plain_default(self):
        r = self.resolve("codex", "medium")
        self.assertEqual(r["model"], "gpt-5.3-codex")
        self.assertIn("no 'medium' level", r["note"])

    def test_family_without_levels(self):
        r = self.resolve("composer", "medium")
        self.assertEqual(r["model"], "composer-2.5")
        self.assertIn("no effort levels", r["note"])

    def test_fast_variants_are_not_picked_by_alias(self):
        self.assertFalse(self.resolve("grok")["model"].endswith("-fast"))

    def test_exact_id_fixes_effort(self):
        r = self.resolve("grok-4.7-high-fast", "low")
        self.assertEqual(r["model"], "grok-4.7-high-fast")
        self.assertIn("--effort ignored", r["note"])

    def test_explicit_family(self):
        self.assertEqual(self.resolve("cursor-grok-4.6", "low")["model"], "cursor-grok-4.6-low")

    def test_synonyms_and_none_level(self):
        self.assertEqual(self.resolve("gpt-5.5", "extra-high")["model"], "gpt-5.5-extra-high")
        self.assertEqual(self.resolve("gpt-5.5", "none")["model"], "gpt-5.5-none")

    def test_default_effort(self):
        self.assertEqual(self.resolve("grok", "default")["model"], "grok-4.7-medium")

    def test_unknown_model(self):
        self.assertIsNone(self.resolve("nonsense")["model"])

    def test_no_list_passes_through(self):
        r = cr.resolve_model("grok-4.7-high", [], "high")
        self.assertEqual(r["model"], "grok-4.7-high")
        self.assertFalse(r["verified"])


class GitChanges(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.git("init", "-q")
        self.write("a.txt", "one\n")
        self.write("b.txt", "two\n")
        self.git("add", "-A")
        self.git("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "init")

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args):
        subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True)

    def write(self, rel, text):
        path = Path(self.root) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def test_detects_new_and_edited_files_but_not_untouched_dirty_ones(self):
        self.write("a.txt", "user edit\n")  # dirty before the run, left alone by it
        before = cr.snapshot(self.root)
        self.write("b.txt", "agent edit\n")
        self.write("new/c.txt", "agent file\n")
        after = cr.snapshot(self.root)
        changed, head_moved = cr.changes_between(self.root, before, after)
        self.assertEqual(changed, ["b.txt", "new/c.txt"])
        self.assertFalse(head_moved)

    def test_detects_edit_on_top_of_a_dirty_file(self):
        self.write("a.txt", "user edit\n")
        before = cr.snapshot(self.root)
        self.write("a.txt", "user edit\nagent edit\n")
        changed, _ = cr.changes_between(self.root, before, cr.snapshot(self.root))
        self.assertEqual(changed, ["a.txt"])

    def test_detects_a_commit(self):
        before = cr.snapshot(self.root)
        self.write("b.txt", "committed by agent\n")
        self.git("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qam", "agent")
        changed, head_moved = cr.changes_between(self.root, before, cr.snapshot(self.root))
        self.assertTrue(head_moved)
        self.assertEqual(changed, ["b.txt"])

    def test_no_changes(self):
        before = cr.snapshot(self.root)
        changed, head_moved = cr.changes_between(self.root, before, cr.snapshot(self.root))
        self.assertEqual((changed, head_moved), ([], False))


class ChatIds(unittest.TestCase):
    def test_validation(self):
        self.assertTrue(cr.CHAT_ID_RE.match("e5c09996-a328-4182-823a-a00667d11d3b"))
        self.assertFalse(cr.CHAT_ID_RE.match("--force"))
        self.assertFalse(cr.CHAT_ID_RE.match("abc; rm -rf /"))


if __name__ == "__main__":
    unittest.main()
