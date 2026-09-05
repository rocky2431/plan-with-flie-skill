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

    def test_nested_discovery_stops_at_the_nearest_git_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir).resolve()
            task = root / ".tasks" / "feature.md"
            task.parent.mkdir()
            task.write_text("# The parent task\n", encoding="utf-8")
            nested = root / "src" / "nested"
            nested.mkdir(parents=True)

            found = self.runtime.resolve_state(nested)
            self.assertEqual("found", found.status)
            self.assertEqual(root, found.root)
            self.assertEqual(".tasks/feature.md", found.relative_path)

            # A worktree's .git can be a file, not a directory.
            (nested / ".git").write_text("gitdir: unused-in-this-fixture\n")
            self.assertEqual("missing", self.runtime.resolve_state(nested).status)
            self.assertEqual("found", self.runtime.resolve_state(root, task="feature", discover=False).status)

    def test_multiple_tasks_require_selection_and_archives_are_not_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tasks = root / ".tasks"
            tasks.mkdir()
            for name in ("alpha", "beta"):
                (tasks / f"{name}.md").write_text(name, encoding="utf-8")
            (tasks / "archive").mkdir()
            (tasks / "archive" / "finished.md").write_text("finished", encoding="utf-8")

            ambiguous = self.runtime.resolve_state(root)
            self.assertEqual("ambiguous", ambiguous.status)
            self.assertEqual((".tasks/alpha.md", ".tasks/beta.md"), ambiguous.candidates)
            selected = self.runtime.resolve_state(root, task="beta")
            self.assertEqual(".tasks/beta.md", selected.relative_path)
            self.assertEqual("invalid", self.runtime.resolve_state(root, task="absent").status)
            archived = self.runtime.resolve_state(root, state_file=".tasks/archive/finished.md")
            self.assertEqual("found", archived.status)

    def test_legacy_selection_stays_stable_when_named_tasks_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "work").mkdir()
            (root / "work" / "task-state.md").write_text("legacy", encoding="utf-8")
            (root / ".tasks").mkdir()
            (root / ".tasks" / "feature.md").write_text("named", encoding="utf-8")

            self.assertEqual("work/task-state.md", self.runtime.resolve_state(root).relative_path)
            self.assertEqual(".tasks/feature.md", self.runtime.resolve_state(root, task="feature").relative_path)


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

    def test_small_record_is_intact_even_with_a_long_judgment_section(self) -> None:
        body = "# Task\n\n## Current understanding\nStill in progress.\n\n## Judgments and corrections\n"
        body += "Observed detail. " * 110
        body += "\nThe earlier conclusion was refuted; verification is still pending.\n"
        rendered = self.runtime.render_recovery_context(relative_path=".tasks/fix.md", text=body)

        self.assertTrue(rendered.endswith(body))
        self.assertNotIn("PARTIAL RECOVERY PREVIEW", rendered)

    def test_large_preview_labels_omission_and_never_slices_a_section(self) -> None:
        current = "## Current understanding\nThe latest user correction changes S2, not S1.\n"
        oversized = "## Judgments and corrections\nBEGIN-LONG-SECTION\n" + "detail\n" * 2000 + "END-LONG-SECTION\n"
        evidence = "## Evidence and artifacts\nE1: check the saved producer contract.\n"
        rendered = self.runtime.render_recovery_context(
            relative_path=".tasks/fix.md", text=current + oversized + evidence,
        )

        self.assertIn("PARTIAL RECOVERY PREVIEW", rendered)
        self.assertIn("Read the complete record", rendered)
        self.assertIn(current.strip(), rendered)
        self.assertIn(evidence.strip(), rendered)
        self.assertNotIn("BEGIN-LONG-SECTION", rendered)
        self.assertNotIn("END-LONG-SECTION", rendered)
        self.assertLessEqual(len(rendered), self.runtime.MAX_CONTEXT_CHARS)

    def test_extreme_identity_keeps_the_recovery_output_bounded(self) -> None:
        rendered = self.runtime.render_recovery_context(relative_path="a/" * 5000 + "task.md", text="state")
        self.assertIn("Recovery skipped", rendered)
        self.assertLessEqual(len(rendered), self.runtime.MAX_CONTEXT_CHARS)

    def test_headings_inside_fenced_evidence_are_not_promoted_to_recovery_steps(self) -> None:
        for fence in ("```markdown", "~~~markdown"):
            with self.subTest(fence=fence):
                body = "## Evidence and artifacts\n" + "detail\n" * 2000
                body += f"{fence}\n## Next action\nEXAMPLE-ONLY-ACTION\n{fence[:3]}\n"
                body += "## Current understanding\nThe real task is unfinished.\n"
                rendered = self.runtime.render_recovery_context(relative_path=".tasks/example.md", text=body)
                self.assertIn("The real task is unfinished", rendered)
                self.assertNotIn("EXAMPLE-ONLY-ACTION", rendered)


class TaskStateCliTests(unittest.TestCase):
    def run_cli(self, root: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CLI_PATH), *args, "--root", str(root)],
            text=True,
            capture_output=True,
            env={key: value for key, value in os.environ.items() if not key.startswith("TASK_STATE_")},
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

    def test_named_tasks_are_idempotent_and_read_returns_the_complete_selected_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            first = self.run_cli(root, "init", "--task", "feature", "--objective", "Finish the requested behavior")
            self.assertEqual(0, first.returncode, first.stderr)
            task = root / ".tasks" / "feature.md"
            content = task.read_text(encoding="utf-8")
            self.assertIn("Finish the requested behavior", content)
            self.assertNotIn("{{", content)
            content += "\nObserved evidence. " * 1000 + "\nFinal caveat: acceptance is unverified.\n"
            task.write_text(content, encoding="utf-8")
            again = self.run_cli(root, "init", "--task", "feature", "--objective", "Must not overwrite")
            second = self.run_cli(root, "init", "--task", "other", "--objective", "Unrelated task")
            self.assertEqual(0, again.returncode, again.stderr)
            self.assertEqual(0, second.returncode, second.stderr)
            self.assertFalse((root / "work").exists())

            ambiguous = self.run_cli(root, "resolve")
            self.assertEqual(2, ambiguous.returncode)
            self.assertEqual("ambiguous", json.loads(ambiguous.stdout)["status"])
            selected = self.run_cli(root, "read", "--task", "feature")
            self.assertEqual(0, selected.returncode, selected.stderr)
            self.assertEqual(content, selected.stdout)
            missing = self.run_cli(root, "read", "--task", "absent")
            self.assertEqual(2, missing.returncode)
            self.assertEqual("", missing.stdout)

    def test_objective_text_is_not_reinterpreted_as_template_syntax(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            objective = "Support literal {{TASK_ID}} and {{STATE_PATH}} in user input."
            result = self.run_cli(root, "init", "--task", "literal", "--objective", objective)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn(objective, (root / ".tasks" / "literal.md").read_text(encoding="utf-8"))

    def test_resolve_keeps_json_diagnostics_for_an_unavailable_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_cli(Path(tmpdir) / "absent", "resolve")
            self.assertEqual(2, result.returncode)
            self.assertEqual("invalid", json.loads(result.stdout)["status"])
            self.assertEqual("", result.stderr)

    def test_read_uses_root_and_task_pins_but_explicit_file_takes_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as elsewhere:
            root = Path(tmpdir)
            (root / ".tasks").mkdir()
            (root / ".tasks" / "selected.md").write_text("selected task\n", encoding="utf-8")
            (root / "another file.md").write_text("explicit file\n", encoding="utf-8")
            env = {key: value for key, value in os.environ.items() if not key.startswith("TASK_STATE_")}
            env.update(TASK_STATE_ROOT=str(root), TASK_STATE_TASK="selected")
            for args, expected in (([], "selected task\n"), (["--file", "another file.md"], "explicit file\n")):
                with self.subTest(args=args):
                    result = subprocess.run([sys.executable, str(CLI_PATH), "read", *args], cwd=elsewhere,
                                            env=env, text=True, capture_output=True, check=False)
                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assertEqual(expected, result.stdout)

    def test_named_creation_cannot_escape_through_ids_or_symlinked_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as outside_dir:
            root = Path(tmpdir)
            invalid = self.run_cli(root, "init", "--task", "../escape", "--objective", "Not permitted")
            self.assertEqual(2, invalid.returncode)
            self.assertFalse((root / ".tasks").exists())
            try:
                (root / ".tasks").symlink_to(Path(outside_dir), target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlinks unavailable: {exc}")
            escaped = self.run_cli(root, "init", "--task", "escape", "--objective", "Not permitted")
            self.assertEqual(2, escaped.returncode)
            self.assertEqual([], list(Path(outside_dir).iterdir()))

    def test_handoff_requires_the_actual_record_in_the_receiving_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as destination_dir:
            source, destination = Path(source_dir), Path(destination_dir)
            created = self.run_cli(source, "init", "--task", "handoff", "--objective", "Continue the same task")
            self.assertEqual(0, created.returncode, created.stderr)
            missing = self.run_cli(destination, "read", "--task", "handoff")
            self.assertEqual(2, missing.returncode)
            self.assertEqual("", missing.stdout)

            content = (source / ".tasks" / "handoff.md").read_text(encoding="utf-8")
            (destination / ".tasks").mkdir()
            (destination / ".tasks" / "handoff.md").write_text(content, encoding="utf-8")
            received = self.run_cli(destination, "read", "--task", "handoff")
            self.assertEqual(0, received.returncode, received.stderr)
            self.assertEqual(content, received.stdout)


if __name__ == "__main__":
    unittest.main()
