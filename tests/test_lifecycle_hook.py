from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = (
    REPO_ROOT
    / "plugins"
    / "task-state-with-files"
    / "skills"
    / "task-state-with-files"
)
HOOK_PATH = SKILL_ROOT / "scripts" / "lifecycle_hook.py"


class CrossHostLifecycleHookTests(unittest.TestCase):
    def run_hook(
        self,
        host: str,
        root: Path,
        *,
        event: str,
        source: str | None = None,
        disabled: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        payload: dict[str, object] = {
            "session_id": "test-session",
            "cwd": str(root),
            "hook_event_name": event,
        }
        if source is not None:
            payload["source"] = source
        env = os.environ.copy()
        if disabled:
            env["TASK_STATE_DISABLED"] = "1"
        return subprocess.run(
            [sys.executable, str(HOOK_PATH), "--host", host],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )

    @staticmethod
    def write_state(root: Path, marker: str) -> None:
        state = root / "work" / "task-state.md"
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(
            f"# Task State\n\n## Next action\n{marker}\n",
            encoding="utf-8",
        )

    def test_kimi_user_prompt_emits_plain_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_state(root, "KIMI-RECOVERY-MARKER")
            result = self.run_hook("kimi", root, event="UserPromptSubmit")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("KIMI-RECOVERY-MARKER", result.stdout)
        self.assertFalse(result.stdout.lstrip().startswith("{"))

    def test_kimi_observation_hooks_do_not_claim_context_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_state(root, "MUST-NOT-APPEAR")
            for event, source in (("SessionStart", "startup"),
                                  ("SessionStart", "resume"),
                                  ("PostCompact", None), ("TurnStarted", None)):
                with self.subTest(event=event, source=source):
                    result = self.run_hook("kimi", root, event=event, source=source)
                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assertEqual("", result.stdout)

    def test_kimi_each_prompt_reads_current_state_without_a_stale_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_state(root, "FIRST-STATE")
            first = self.run_hook("kimi", root, event="UserPromptSubmit")
            self.write_state(root, "UPDATED-STATE")
            second = self.run_hook("kimi", root, event="UserPromptSubmit")
            self.assertIn("FIRST-STATE", first.stdout)
            self.assertIn("UPDATED-STATE", second.stdout)
            self.assertNotIn("FIRST-STATE", second.stdout)
            self.assertLessEqual(len(second.stdout), 8001)

    def test_claude_and_zcode_emit_strict_session_start_json(self) -> None:
        for host in ("claude", "zcode"):
            with self.subTest(host=host), tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                self.write_state(root, f"{host.upper()}-RECOVERY-MARKER")
                result = self.run_hook(
                    host, root, event="SessionStart", source="compact"
                )

                self.assertEqual(0, result.returncode, result.stderr)
                payload = json.loads(result.stdout)
                self.assertEqual(
                    {"hookSpecificOutput"},
                    set(payload),
                )
                output = payload["hookSpecificOutput"]
                self.assertEqual(
                    {"hookEventName", "additionalContext"},
                    set(output),
                )
                self.assertEqual("SessionStart", output["hookEventName"])
                self.assertIn(
                    f"{host.upper()}-RECOVERY-MARKER",
                    output["additionalContext"],
                )

    def test_missing_state_and_opt_out_are_silent_for_every_host(self) -> None:
        for host, event, source in (
            ("kimi", "UserPromptSubmit", None),
            ("zcode", "SessionStart", "resume"),
            ("claude", "SessionStart", "resume"),
        ):
            with self.subTest(host=host), tempfile.TemporaryDirectory() as tmpdir:
                missing = self.run_hook(
                    host, Path(tmpdir), event=event, source=source
                )
                self.write_state(Path(tmpdir), "DISABLED-MARKER")
                disabled = self.run_hook(
                    host,
                    Path(tmpdir),
                    event=event,
                    source=source,
                    disabled=True,
                )

            self.assertEqual("", missing.stdout)
            self.assertEqual("", disabled.stdout)

    def test_stop_never_restores_or_blocks(self) -> None:
        for host in ("kimi", "zcode", "claude"):
            with self.subTest(host=host), tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                self.write_state(root, "MUST-NOT-APPEAR")
                result = self.run_hook(host, root, event="Stop")

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("", result.stdout)


if __name__ == "__main__":
    unittest.main()
