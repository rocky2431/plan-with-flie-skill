from __future__ import annotations

import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = REPO_ROOT / "plugins" / "task-state-with-files"
SKILL_ROOT = PLUGIN_ROOT / "skills" / "task-state-with-files"


class PackageSurfaceTests(unittest.TestCase):
    def test_plugin_manifest_and_marketplace_names_match(self) -> None:
        plugin = json.loads(
            (PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        marketplace = json.loads(
            (REPO_ROOT / ".agents" / "plugins" / "marketplace.json").read_text(
                encoding="utf-8"
            )
        )
        entry = marketplace["plugins"][0]

        self.assertEqual("task-state-with-files", plugin["name"])
        self.assertEqual(plugin["name"], entry["name"])
        self.assertEqual("./skills/", plugin["skills"])
        self.assertEqual("./plugins/task-state-with-files", entry["source"]["path"])

    def test_skill_has_no_scaffold_placeholders(self) -> None:
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertNotIn("TODO", skill)
        self.assertIn("work/task-state.md", skill)
        self.assertIn("SessionStart", skill)
        self.assertIn("Never", skill)

    def test_tracked_package_contains_no_machine_specific_user_path(self) -> None:
        offenders: list[str] = []
        machine_path = "/Users/" + "rocky243"
        for path in REPO_ROOT.rglob("*"):
            if not path.is_file() or ".git" in path.parts:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if machine_path in text:
                offenders.append(str(path.relative_to(REPO_ROOT)))

        self.assertEqual([], offenders)


if __name__ == "__main__":
    unittest.main()
