from __future__ import annotations

import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = REPO_ROOT / "plugins" / "task-state-with-files"
SKILL_ROOT = PLUGIN_ROOT / "skills" / "task-state-with-files"


class PackageSurfaceTests(unittest.TestCase):
    def test_bundled_scripts_stay_importable_on_older_python(self):
        # Hooks run the host's python3, which can be macOS's 3.9: annotations must stay lazy
        # and nothing may need 3.11-only names such as datetime.UTC.
        scripts = sorted((SKILL_ROOT / "scripts").glob("*.py")) + sorted((PLUGIN_ROOT / "hooks").glob("*.py"))
        self.assertTrue(scripts)
        for path in scripts:
            text = path.read_text(encoding="utf-8")
            self.assertIn("from __future__ import annotations", text, path.name)
            self.assertNotRegex(text, r"from datetime import[^\n]*\bUTC\b", path.name)

    def test_claude_zcode_share_registration_with_opposite_host_guards(self):
        config = json.loads((PLUGIN_ROOT / 'hooks/hooks.json').read_text(encoding='utf-8'))
        self.assertEqual({'SessionStart', 'PostToolUse', 'Stop'}, set(config['hooks']))
        post = config['hooks']['PostToolUse'][0]['hooks'][0]
        stop = config['hooks']['Stop'][0]['hooks'][0]
        self.assertIn('if [ -n "${ZCODE_PLUGIN_ROOT:-}" ]', post['command'])
        self.assertNotIn('--host claude', post['command'])
        self.assertIn('if defined ZCODE_PLUGIN_ROOT', post['commandWindows'])
        self.assertIn('--host zcode', post['commandWindows'])
        self.assertIn('if [ -z "${ZCODE_PLUGIN_ROOT:-}" ]', stop['command'])
        self.assertNotIn('--host zcode', stop['command'])
        self.assertIn('if not defined ZCODE_PLUGIN_ROOT', stop['commandWindows'])
        self.assertIn('--host claude', stop['commandWindows'])
        for entry in (post, stop):
            self.assertEqual('command', entry['type'])
            self.assertEqual(10, entry['timeout'])

    def test_native_manifests_share_one_skill_tree(self) -> None:
        plugin = REPO_ROOT / "plugins/task-state-with-files"
        expected = json.loads((plugin / ".codex-plugin/plugin.json").read_text())
        for relative in (".claude-plugin/plugin.json", ".zcode-plugin/plugin.json", "kimi.plugin.json"):
            manifest = json.loads((plugin / relative).read_text())
            self.assertEqual(manifest["name"], expected["name"])
            self.assertEqual(manifest["version"], expected["version"])
        self.assertTrue((plugin / "skills/task-state-with-files/SKILL.md").is_file())

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
