"""Exercise session-scoped activation through all shipped hook executables."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from subprocess_environment import clean_environment


PLUGIN = Path(__file__).resolve().parents[1] / "plugins/task-state-with-files"
SCRIPTS = PLUGIN / "skills/task-state-with-files/scripts"
CLI = SCRIPTS / "task_state.py"


class SessionSelectionTests(unittest.TestCase):
    def run_cli(self, root, *args):
        env = clean_environment()
        return subprocess.run([sys.executable, str(CLI), *args, "--root", str(root)],
                              env=env, capture_output=True, text=True)

    def hook(self, host, root, session, **pins):
        env = clean_environment()
        env.update(pins, PLUGIN_ROOT=str(PLUGIN))
        command = ([str(PLUGIN / "hooks/session_start.py")] if host == "codex" else
                   [str(SCRIPTS / "lifecycle_hook.py"), "--host", host])
        event = {"cwd": str(root), "session_id": session, "source": "resume",
                 "hook_event_name": "UserPromptSubmit" if host == "kimi" else "SessionStart"}
        result = subprocess.run([sys.executable, *command], input=json.dumps(event),
                                env=env, capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stderr)
        return result.stdout

    def test_activation_recovery_isolation_and_deactivation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".tasks").mkdir()
            (root / ".tasks/alpha.md").write_text("Keep the existing evidence. Next: verify alpha.\n")
            for host in ("codex", "claude", "zcode", "kimi"):
                self.assertEqual("", self.hook(host, root, "session-a"))
            # Active read retains legacy discovery; merely reading does not activate hooks.
            self.assertIn("verify alpha", self.run_cli(root, "read").stdout)
            selected = self.run_cli(root, "activate", "--task", "alpha", "--session", "session-a")
            self.assertEqual(0, selected.returncode, selected.stderr)
            (root / ".tasks/beta.md").write_text("Next: verify beta.\n")
            selected_b = self.run_cli(root, "activate", "--task", "beta", "--session", "session-b")
            self.assertEqual(0, selected_b.returncode, selected_b.stderr)
            # First recovery seeds passing copies; subsequent recovery is read-only.
            self.assertIn("verify alpha", self.hook("codex", root, "session-a"))
            self.assertIn("verify beta", self.hook("codex", root, "session-b"))
            before = {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            for host in ("codex", "claude", "zcode", "kimi"):
                with self.subTest(host=host):
                    self.assertIn("verify alpha", self.hook(host, root, "session-a"))
                    self.assertNotIn("verify beta", self.hook(host, root, "session-a"))
                    self.assertIn("verify beta", self.hook(host, root, "session-b"))
                    self.assertEqual("", self.hook(host, root, "unrelated"))
                    self.assertEqual("", self.hook(host, root, None))
                    self.assertEqual("", self.hook(host, root, "session-a", TASK_STATE_DISABLED="1"))
                    self.assertIn("Recovery skipped", self.hook(host, root, "unrelated", TASK_STATE_TASK="absent"))
            self.assertEqual(before, {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()})
            conflict = self.run_cli(root, "activate", "--task", "beta", "--session", "session-a")
            self.assertNotEqual(0, conflict.returncode)
            self.assertEqual(0, self.run_cli(root, "deactivate", "--session", "session-a").returncode)
            for host in ("codex", "claude", "zcode", "kimi"):
                self.assertEqual("", self.hook(host, root, "session-a"))
                self.assertIn("verify beta", self.hook(host, root, "session-b"))

    def test_exact_business_file_and_invalid_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs").mkdir()
            (root / "docs/progress.md").write_text("BUSINESS-STATE\n")
            self.assertNotEqual(0, self.run_cli(root, "activate", "--session", "a").returncode)
            for path in ("../outside.md", "/tmp/outside.md", "missing.md"):
                self.assertNotEqual(0, self.run_cli(root, "activate", "--file", path, "--session", "a").returncode)
            result = self.run_cli(root, "activate", "--file", "docs/progress.md", "--session", "a")
            self.assertEqual(0, result.returncode, result.stderr)
            for host in ("codex", "claude", "zcode", "kimi"):
                self.assertIn("BUSINESS-STATE", self.hook(host, root, "a"))
                self.assertIn("BUSINESS-STATE", self.hook(host, root, "b", TASK_STATE_FILE="docs/progress.md"))
                self.assertIn("Recovery skipped", self.hook(host, root, "a", TASK_STATE_FILE="docs/progress.md", TASK_STATE_TASK="other"))
            (root / "docs/progress.md").unlink()
            self.assertIn("Recovery skipped", self.hook("codex", root, "a"))

    def test_unselected_invalid_roots_are_silent_and_selected_roots_are_diagnostic(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ordinary_file = root / "file"
            ordinary_file.write_text("not a directory\n")
            for host in ("codex", "claude", "zcode", "kimi"):
                self.assertEqual("", self.hook(host, ordinary_file, "unselected"))
                self.assertEqual("", self.hook(host, root, "unselected", TASK_STATE_ROOT=str(root / "absent")))
                self.assertIn("Recovery skipped", self.hook(host, ordinary_file, "a", TASK_STATE_TASK="selected"))
                self.assertIn("Recovery skipped", self.hook(host, root, "a", TASK_STATE_ROOT=str(root / "absent"), TASK_STATE_FILE="note.md"))

    @unittest.skipIf(os.name == "nt", "Symlink creation needs privileges on Windows")
    def test_session_bindings_cannot_escape_workspace(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as other:
            root, outside = Path(tmp), Path(other)
            (root / ".tasks").mkdir()
            (root / ".tasks/alpha.md").write_text("ALPHA\n")
            selected = self.run_cli(root, "activate", "--task", "alpha", "--session", "a")
            self.assertEqual(0, selected.returncode, selected.stderr)
            binding = root / selected.stdout.strip()
            victim = outside / "private.ref"
            victim.write_text("UNCHANGED\n")
            binding.unlink()
            binding.symlink_to(victim)
            self.assertNotEqual(0, self.run_cli(root, "activate", "--task", "alpha", "--session", "a").returncode)
            self.assertNotEqual(0, self.run_cli(root, "deactivate", "--session", "a").returncode)
            for host in ("codex", "claude", "zcode", "kimi"):
                output = self.hook(host, root, "a")
                self.assertIn("Recovery skipped", output)
                self.assertNotIn("UNCHANGED", output)
            self.assertEqual("UNCHANGED\n", victim.read_text())


if __name__ == "__main__":
    unittest.main()
