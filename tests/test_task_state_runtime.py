from __future__ import annotations

import importlib.util
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
RUNTIME_PATH = SKILL_ROOT / "scripts" / "task_state_runtime.py"
CLI_PATH = SKILL_ROOT / "scripts" / "task_state.py"


def load_runtime():
    spec = importlib.util.spec_from_file_location("task_state_runtime", RUNTIME_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TaskStateResolutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime = load_runtime()

    def test_session_state_resolves_relative_to_current_task_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state = root / "work" / "task-state.md"
            state.parent.mkdir()
            state.write_text("# Task State\n", encoding="utf-8")

            result = self.runtime.resolve_state(root)

        self.assertEqual("found", result.status)
        self.assertEqual("work/task-state.md", result.relative_path)
        self.assertEqual(state.resolve(), result.path)

    def test_repository_shared_state_uses_a_relative_local_binding(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            shared = root / "docs" / "wip" / "feature.md"
            shared.parent.mkdir(parents=True)
            shared.write_text("# Task State\n", encoding="utf-8")
            ref = root / "work" / "task-state.ref"
            ref.parent.mkdir()
            ref.write_text("docs/wip/feature.md\n", encoding="utf-8")

            result = self.runtime.resolve_state(root)

        self.assertEqual("found", result.status)
        self.assertEqual("docs/wip/feature.md", result.relative_path)
        self.assertEqual(shared.resolve(), result.path)

    def test_direct_state_and_binding_together_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            work = root / "work"
            work.mkdir()
            (work / "task-state.md").write_text("# direct\n", encoding="utf-8")
            (work / "task-state.ref").write_text("docs/wip/other.md\n", encoding="utf-8")

            result = self.runtime.resolve_state(root)

        self.assertEqual("invalid", result.status)
        self.assertIn("both", result.message.lower())

    def test_absolute_binding_fails_closed_without_leaking_the_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            ref = root / "work" / "task-state.ref"
            ref.parent.mkdir()
            ref.write_text("/private/tmp/secret-state.md\n", encoding="utf-8")

            result = self.runtime.resolve_state(root)

        self.assertEqual("invalid", result.status)
        self.assertIn("relative", result.message.lower())
        self.assertNotIn("/private/tmp", result.message)

    def test_parent_traversal_binding_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            ref = root / "work" / "task-state.ref"
            ref.parent.mkdir()
            ref.write_text("../outside.md\n", encoding="utf-8")

            result = self.runtime.resolve_state(root)

        self.assertEqual("invalid", result.status)
        self.assertIn("parent traversal", result.message.lower())

    def test_symlink_escape_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as outside_dir:
            root = Path(tmpdir)
            outside = Path(outside_dir) / "state.md"
            outside.write_text("# outside\n", encoding="utf-8")
            direct = root / "work" / "task-state.md"
            direct.parent.mkdir()
            try:
                direct.symlink_to(outside)
            except OSError as exc:
                self.skipTest(f"symlinks unavailable: {exc}")

            result = self.runtime.resolve_state(root)

        self.assertEqual("invalid", result.status)
        self.assertIn("outside", result.message.lower())

    def test_symlink_loop_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            direct = root / "work" / "task-state.md"
            direct.parent.mkdir()
            try:
                direct.symlink_to(direct)
            except OSError as exc:
                self.skipTest(f"symlinks unavailable: {exc}")

            result = self.runtime.resolve_state(root)

        self.assertEqual("invalid", result.status)
        self.assertIn("resolve", result.message.lower())

    def test_missing_state_is_silent_not_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.runtime.resolve_state(Path(tmpdir))

        self.assertEqual("missing", result.status)
        self.assertIsNone(result.path)


class RecoveryRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime = load_runtime()

    def test_renderer_preserves_next_action_and_uses_only_relative_identity(self) -> None:
        body = """# Task State: Example

## Objective and scope
Ship the accepted local workflow.

## Current state
- [ ] Finish the hook.

## Actions and verification
{}

## Next action
Run the compact recovery smoke.

## Not done / do not redo
- Do not add a Stop gate.
""".format("- evidence\n" * 2000)

        rendered = self.runtime.render_recovery_context(
            relative_path="work/task-state.md",
            text=body,
        )

        self.assertIn("work/task-state.md", rendered)
        self.assertIn("Run the compact recovery smoke", rendered)
        self.assertIn("Do not add a Stop gate", rendered)
        self.assertIn("does not authorize automatic continuation", rendered)
        self.assertLessEqual(len(rendered), self.runtime.MAX_CONTEXT_CHARS)
        self.assertNotIn(str(Path.cwd()), rendered)


class TaskStateCliTests(unittest.TestCase):
    def run_cli(self, root: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CLI_PATH), *args, "--root", str(root)],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_init_is_idempotent_and_creates_the_session_local_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            first = self.run_cli(root, "init", "--objective", "Verify recovery")
            second = self.run_cli(root, "init", "--objective", "Ignored replacement")
            state = root / "work" / "task-state.md"

            self.assertEqual(0, first.returncode, first.stderr)
            self.assertEqual(0, second.returncode, second.stderr)
            content = state.read_text(encoding="utf-8")

        self.assertIn("Verify recovery", content)
        self.assertNotIn("Ignored replacement", content)

    def test_bind_writes_only_a_relative_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            shared = root / "docs" / "wip" / "shared.md"
            shared.parent.mkdir(parents=True)
            shared.write_text("# shared\n", encoding="utf-8")

            result = self.run_cli(root, "bind", "docs/wip/shared.md")

            self.assertEqual(0, result.returncode, result.stderr)
            ref_text = (root / "work" / "task-state.ref").read_text(encoding="utf-8")

        self.assertEqual("docs/wip/shared.md\n", ref_text)
        self.assertFalse(os.path.isabs(ref_text.strip()))


if __name__ == "__main__":
    unittest.main()
