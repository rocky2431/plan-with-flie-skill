from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = REPO_ROOT / "scripts" / "install_user.py"
HOSTS = ("kimi", "zcode", "claude", "hermes")


class CrossHostUserInstallerTests(unittest.TestCase):
    def run_installer(
        self,
        home: Path,
        command: str,
        *extra: str,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(INSTALLER),
                command,
                "--home",
                str(home),
                "--hosts",
                ",".join(HOSTS),
                *extra,
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    @staticmethod
    def seed_configs(home: Path) -> None:
        kimi = home / ".kimi-code" / "config.toml"
        kimi.parent.mkdir(parents=True)
        kimi.write_text('theme = "dark"\nhooks = []\n', encoding="utf-8")

        zcode = home / ".zcode" / "cli" / "config.json"
        zcode.parent.mkdir(parents=True)
        zcode.write_text(
            json.dumps(
                {
                    "hooks": {
                        "enabled": True,
                        "events": {
                            "SessionStart": [
                                {
                                    "matcher": "startup",
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": "python3 existing-zcode.py",
                                        }
                                    ],
                                }
                            ]
                        },
                    },
                    "provider": {"keep": True},
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        claude = home / ".claude" / "settings.json"
        claude.parent.mkdir(parents=True)
        claude.write_text(
            json.dumps(
                {
                    "hooks": {
                        "SessionStart": [
                            {
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": "node existing-claude.js",
                                    }
                                ]
                            }
                        ]
                    },
                    "language": "Chinese",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def test_install_is_idempotent_and_preserves_foreign_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            self.seed_configs(home)
            backup = home / "backups"
            first = self.run_installer(
                home, "install", "--backup-dir", str(backup)
            )
            second = self.run_installer(
                home, "install", "--backup-dir", str(backup / "second")
            )

            self.assertEqual(0, first.returncode, first.stderr)
            self.assertEqual(0, second.returncode, second.stderr)

            for relative in (
                ".kimi-code/skills/task-state-with-files/SKILL.md",
                ".zcode/skills/task-state-with-files/SKILL.md",
                ".claude/skills/task-state-with-files/SKILL.md",
                ".hermes/skills/task-state-with-files/SKILL.md",
            ):
                self.assertTrue((home / relative).is_file(), relative)

            kimi_text = (home / ".kimi-code" / "config.toml").read_text(
                encoding="utf-8"
            )
            kimi = tomllib.loads(kimi_text)
            self.assertEqual("dark", kimi["theme"])
            self.assertEqual(["UserPromptSubmit"], [h["event"] for h in kimi["hooks"]])
            self.assertEqual(1, kimi_text.count("BEGIN task-state-with-files"))
            self.assertNotIn(str(home), kimi_text)

            zcode = json.loads(
                (home / ".zcode" / "cli" / "config.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual({"keep": True}, zcode["provider"])
            zcode_entries = zcode["hooks"]["events"]["SessionStart"]
            self.assertEqual(2, len(zcode_entries))
            self.assertIn("existing-zcode.py", json.dumps(zcode_entries[0]))
            self.assertNotIn(str(home), json.dumps(zcode_entries))

            claude = json.loads(
                (home / ".claude" / "settings.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual("Chinese", claude["language"])
            claude_entries = claude["hooks"]["SessionStart"]
            self.assertEqual(2, len(claude_entries))
            self.assertIn("existing-claude.js", json.dumps(claude_entries[0]))
            self.assertNotIn(str(home), json.dumps(claude_entries))

            self.assertTrue((backup / "kimi" / "config.toml").is_file())
            self.assertTrue((backup / "zcode" / "config.json").is_file())
            self.assertTrue((backup / "claude" / "settings.json").is_file())

    def test_doctor_reports_native_recovery_and_hermes_skill_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            self.seed_configs(home)
            install = self.run_installer(
                home, "install", "--backup-dir", str(home / "backups")
            )
            doctor = self.run_installer(home, "doctor", "--json")

        self.assertEqual(0, install.returncode, install.stderr)
        self.assertEqual(0, doctor.returncode, doctor.stderr)
        report = json.loads(doctor.stdout)
        self.assertTrue(report["ok"])
        self.assertEqual("user-prompt", report["hosts"]["kimi"]["recovery"])
        self.assertEqual("native", report["hosts"]["zcode"]["recovery"])
        self.assertEqual("native", report["hosts"]["claude"]["recovery"])
        self.assertEqual("skill-only", report["hosts"]["hermes"]["recovery"])
        self.assertEqual("not-applicable", report["hosts"]["hermes"]["hook"])

    def test_invalid_later_host_config_fails_before_any_host_is_changed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            self.seed_configs(home)
            claude = home / ".claude" / "settings.json"
            claude.write_text(
                json.dumps({"hooks": "not-an-object"}) + "\n",
                encoding="utf-8",
            )

            result = self.run_installer(
                home, "install", "--backup-dir", str(home / "backups")
            )

            self.assertEqual(2, result.returncode)
            for relative in (
                ".kimi-code/skills/task-state-with-files",
                ".zcode/skills/task-state-with-files",
                ".claude/skills/task-state-with-files",
                ".hermes/skills/task-state-with-files",
            ):
                self.assertFalse((home / relative).exists(), relative)
            self.assertNotIn(
                "task-state-with-files",
                (home / ".kimi-code" / "config.toml").read_text(encoding="utf-8"),
            )
            self.assertNotIn(
                "task-state-with-files",
                (home / ".zcode" / "cli" / "config.json").read_text(
                    encoding="utf-8"
                ),
            )

    def test_uninstall_removes_only_managed_skill_and_hook_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            self.seed_configs(home)
            install = self.run_installer(
                home, "install", "--backup-dir", str(home / "backups")
            )
            uninstall = self.run_installer(
                home, "uninstall", "--backup-dir", str(home / "uninstall-backup")
            )

            self.assertEqual(0, install.returncode, install.stderr)
            self.assertEqual(0, uninstall.returncode, uninstall.stderr)
            for relative in (
                ".kimi-code/skills/task-state-with-files",
                ".zcode/skills/task-state-with-files",
                ".claude/skills/task-state-with-files",
                ".hermes/skills/task-state-with-files",
            ):
                self.assertFalse((home / relative).exists(), relative)

            zcode_text = (home / ".zcode" / "cli" / "config.json").read_text(
                encoding="utf-8"
            )
            claude_text = (home / ".claude" / "settings.json").read_text(
                encoding="utf-8"
            )
            kimi_text = (home / ".kimi-code" / "config.toml").read_text(
                encoding="utf-8"
            )
            self.assertIn("existing-zcode.py", zcode_text)
            self.assertIn("existing-claude.js", claude_text)
            self.assertEqual("dark", tomllib.loads(kimi_text)["theme"])
            self.assertNotIn("task-state-with-files", zcode_text)
            self.assertNotIn("task-state-with-files", claude_text)
            self.assertNotIn("task-state-with-files", kimi_text)

    def test_kimi_custom_root_migrates_old_hooks_and_executes_recovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            custom = home / "custom kimi home"
            custom.mkdir()
            config = custom / "config.toml"
            config.write_text('''theme = "dark"
[[hooks]]
event = "UserPromptSubmit"
command = "echo foreign-hook"
# BEGIN task-state-with-files managed hooks
[[hooks]]
event = "SessionStart"
command = "python3 task-state-with-files/scripts/lifecycle_hook.py --host kimi"
[[hooks]]
event = "PostCompact"
command = "python3 task-state-with-files/scripts/lifecycle_hook.py --host kimi"
# END task-state-with-files managed hooks
''')
            env = {**os.environ, "KIMI_CODE_HOME": str(custom)}
            args = [sys.executable, str(INSTALLER), "install", "--home", str(home), "--hosts", "kimi"]
            for _ in range(2):
                install = subprocess.run(args, env=env, capture_output=True, text=True)
                self.assertEqual(0, install.returncode, install.stderr)
            hooks = tomllib.loads(config.read_text())["hooks"]
            self.assertEqual(["UserPromptSubmit", "UserPromptSubmit"], [h["event"] for h in hooks])
            self.assertEqual("echo foreign-hook", hooks[0]["command"])
            workspace = home / "project"
            (workspace / "work").mkdir(parents=True)
            (workspace / "work/task-state.md").write_text("## Next action\nCUSTOM-ROOT-RECOVERY\n")
            if os.name == "posix":  # User hook commands are documented for POSIX hosts.
                result = subprocess.run(hooks[1]["command"], shell=True, cwd=workspace, env=env,
                                        input=json.dumps({"hook_event_name": "UserPromptSubmit", "cwd": str(workspace)}),
                                        text=True, capture_output=True)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertIn("CUSTOM-ROOT-RECOVERY", result.stdout)
            self.assertFalse((home / ".kimi").exists())
            self.assertFalse((home / ".kimi-code").exists())
            args[2] = "doctor"
            doctor = subprocess.run(args + ["--json"], env=env, capture_output=True, text=True)
            self.assertEqual(0, doctor.returncode, doctor.stderr)
            # A right script on the wrong event must not pass the doctor.
            config.write_text(config.read_text().replace('event = "UserPromptSubmit"', 'event = "PostCompact"'))
            stale = subprocess.run(args + ["--json"], env=env, capture_output=True, text=True)
            self.assertEqual(1, stale.returncode)



if __name__ == "__main__":
    unittest.main()
