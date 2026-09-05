from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = REPO_ROOT / "plugins" / "task-state-with-files"
HOOK_PATH = PLUGIN_ROOT / "hooks" / "session_start.py"
HOOKS_JSON = PLUGIN_ROOT / "hooks" / "hooks.json"


class SessionStartHookTests(unittest.TestCase):
    def run_hook(
        self,
        cwd: Path,
        source: str = "compact",
        *,
        disabled: bool = False,
        pins: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = {key: value for key, value in os.environ.items() if not key.startswith("TASK_STATE_")}
        env["PLUGIN_ROOT"] = str(PLUGIN_ROOT)
        env.update(pins or {})
        if disabled:
            env["TASK_STATE_DISABLED"] = "1"
        payload = {
            "session_id": "test-session",
            "cwd": str(cwd),
            "hook_event_name": "SessionStart",
            "source": source,
        }
        return subprocess.run(
            [sys.executable, str(HOOK_PATH)],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )

    def test_compact_restores_state_as_additional_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state = root / "work" / "task-state.md"
            state.parent.mkdir()
            state.write_text(
                "# Task State\n\n## Next action\nVerify the resumed task.\n",
                encoding="utf-8",
            )

            result = self.run_hook(root)

        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        output = payload["hookSpecificOutput"]
        self.assertEqual("SessionStart", output["hookEventName"])
        self.assertIn("Verify the resumed task", output["additionalContext"])
        self.assertNotIn("decision", payload)
        self.assertNotIn("continue", payload)

    def test_missing_state_is_silent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_hook(Path(tmpdir))

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stdout)

    def test_nested_multi_task_recovery_uses_explicit_pins_without_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tasks = root / ".tasks"
            tasks.mkdir()
            (tasks / "alpha.md").write_text("ALPHA-ONLY\n", encoding="utf-8")
            (tasks / "beta.md").write_text("BETA-ONLY\n", encoding="utf-8")
            nested = root / "src"
            nested.mkdir()

            ambiguous = self.run_hook(nested)
            context = json.loads(ambiguous.stdout)["hookSpecificOutput"]["additionalContext"]
            self.assertIn("Recovery skipped", context)
            self.assertIn(".tasks/alpha.md", context)
            self.assertNotIn("ALPHA-ONLY", context)

            selected = self.run_hook(nested, pins={"TASK_STATE_TASK": "beta"})
            context = json.loads(selected.stdout)["hookSpecificOutput"]["additionalContext"]
            self.assertIn("BETA-ONLY", context)
            self.assertNotIn("ALPHA-ONLY", context)
            invalid = self.run_hook(nested, pins={"TASK_STATE_TASK": "absent"})
            self.assertIn("Recovery skipped", invalid.stdout)
            self.assertNotIn("BETA-ONLY", invalid.stdout)

            # An explicit workspace pin also works when the event starts elsewhere.
            elsewhere = root / "other-worktree"
            elsewhere.mkdir()
            (elsewhere / ".git").write_text("gitdir: fixture\n")
            pinned = self.run_hook(elsewhere, pins={"TASK_STATE_ROOT": str(root), "TASK_STATE_TASK": "alpha"})
            self.assertIn("ALPHA-ONLY", pinned.stdout)

    def test_non_object_event_is_silent_and_non_blocking(self) -> None:
        env = os.environ.copy()
        env["PLUGIN_ROOT"] = str(PLUGIN_ROOT)
        result = subprocess.run(
            [sys.executable, str(HOOK_PATH)],
            input="[]",
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stdout)

    def test_invalid_binding_is_model_visible_but_non_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            ref = root / "work" / "task-state.ref"
            ref.parent.mkdir()
            ref.write_text("/private/tmp/forbidden.md\n", encoding="utf-8")

            result = self.run_hook(root, source="resume")

        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn("additionalContext", payload["hookSpecificOutput"])
        self.assertIn("Recovery skipped", payload["hookSpecificOutput"]["additionalContext"])
        self.assertNotIn("decision", payload)

    def test_unmatched_source_is_silent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_hook(Path(tmpdir), source="unsupported")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stdout)

    def test_explicit_one_shot_opt_out_is_silent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state = root / "work" / "task-state.md"
            state.parent.mkdir()
            state.write_text("# Task State\n\n## Next action\nDo not inject me.\n")

            result = self.run_hook(root, disabled=True)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stdout)

    def test_manifest_uses_plugin_root_and_registers_no_stop_hook(self) -> None:
        manifest = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
        self.assertEqual({"SessionStart"}, set(manifest["hooks"]))
        entry = manifest["hooks"]["SessionStart"][0]
        self.assertEqual("^(startup|resume|clear|compact)$", entry["matcher"])
        command = entry["hooks"][0]["command"]
        self.assertIn("$PLUGIN_ROOT", command)
        self.assertNotIn("/Users/", command)


if __name__ == "__main__":
    unittest.main()
