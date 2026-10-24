"""Exercise sensor reports through shipped hook processes and manifests."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_current_state import CLOSE, OPEN, RUNTIME, record
from test_session_selection import PLUGIN, SCRIPTS


class PostToolSensorTests(unittest.TestCase):
    def run_hook(self, host, root, event='PostToolUse', *, session='owner', selected=True, disabled=False, native=False):
        env = {k: v for k, v in os.environ.items()
               if not k.startswith('TASK_STATE_') and not k.endswith('PLUGIN_ROOT')}
        env.update(PLUGIN_ROOT=str(PLUGIN), GROK_PLUGIN_DATA=str(root / 'grok-data'))
        if selected:
            env.update(TASK_STATE_ROOT=str(root), TASK_STATE_FILE='tasks/fix.md')
        if disabled:
            env['TASK_STATE_DISABLED'] = '1'
        payload = {'hook_event_name': event, 'cwd': str(root), 'source': 'compact',
                   'sessionId' if host == 'grok' else 'session_id': session}
        if native:
            env[host.upper() + '_PLUGIN_ROOT'] = str(PLUGIN)
            group = json.loads((PLUGIN / 'hooks/hooks.json').read_text())['hooks'][event][0]
            command = ['/bin/sh', '-c', group['hooks'][0]['command']]
        elif host == 'codex':
            name = 'session_start.py' if event == 'SessionStart' else 'post_tool_use.py'
            command = [sys.executable, str(PLUGIN / 'hooks' / name)]
        else:
            command = [sys.executable, str(SCRIPTS / 'lifecycle_hook.py'), '--host', host]
        result = subprocess.run(command, input=json.dumps(payload), env=env,
                                capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual('', result.stderr)
        return result.stdout

    def assert_report(self, host, output):
        if host == 'kimi':
            self.assertFalse(output.lstrip().startswith('{'))
            context = output
        else:
            payload = json.loads(output)
            self.assertEqual({'hookSpecificOutput'}, set(payload))
            detail = payload['hookSpecificOutput']
            self.assertEqual({'hookEventName', 'additionalContext'}, set(detail))
            self.assertEqual('PostToolUse', detail['hookEventName'])
            context = detail['additionalContext']
        self.assertIn('tasks/fix.md', context)
        self.assertIn('Nothing was blocked.', context)
        self.assertIn('missing their pair', context)
        self.assertIn(RUNTIME.snapshot_relative_path('tasks/fix.md'), context)
        self.assertLessEqual(len(context), 800)

    def test_all_hosts_deliver_report_and_keep_last_good_copy(self):
        for host in ('claude', 'zcode', 'codex', 'grok'):
            with self.subTest(host=host), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                path = root / 'tasks/fix.md'
                path.parent.mkdir()
                path.write_text(record())
                if host == 'grok':
                    # First PostToolUse retains the existing one-time recovery contract.
                    first = self.run_hook(host, root)
                    self.assertIn('Task-state recovery data', first)
                    self.assertEqual(1, len(list((root / 'grok-data/recovery').glob('*.sent'))))
                self.assertEqual('', self.run_hook(host, root))
                snapshot = root / RUNTIME.snapshot_relative_path('tasks/fix.md')
                self.assertEqual(record(), snapshot.read_text())
                path.write_text(OPEN + '\nbroken\n')
                self.assert_report(host, self.run_hook(host, root))
                self.assertEqual('', self.run_hook(host, root))
                path.write_text(OPEN + '\nanother broken state\n')
                self.assertEqual('', self.run_hook(host, root))
                self.assertEqual(record(), snapshot.read_text())

    def test_each_host_is_silent_unselected_disabled_and_unreadable(self):
        for host in ('claude', 'zcode', 'codex', 'grok', 'kimi'):
            with self.subTest(host=host), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                path = root / 'tasks/fix.md'
                path.parent.mkdir()
                path.write_text(OPEN)
                self.assertEqual('', self.run_hook(host, root, selected=False))
                self.assertEqual('', self.run_hook(host, root, disabled=True))
                self.assertFalse((root / '.task-state').exists())
                # Grok needs its existing recovery marker before the sensor path.
                if host == 'grok':
                    path.write_text(record())
                    self.run_hook(host, root)
                path.write_bytes(b'\xff')
                self.assertEqual('', self.run_hook(host, root))

    def test_post_tool_sensor_uses_native_session_binding(self):
        for host in ('claude', 'zcode', 'codex', 'grok'):
            with self.subTest(host=host), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                path = root / 'tasks/fix.md'
                path.parent.mkdir()
                path.write_text(record())
                binding = root / RUNTIME.session_relative_path('owner')
                binding.parent.mkdir(parents=True)
                binding.write_text('tasks/fix.md\n')
                if host == 'grok':
                    self.run_hook(host, root, selected=False)
                self.assertEqual('', self.run_hook(host, root, selected=False))
                path.write_text(OPEN)
                self.assertEqual('', self.run_hook(host, root, selected=False, session='other'))
                self.assert_report(host, self.run_hook(host, root, selected=False))

    @unittest.skipIf(os.name == 'nt', 'POSIX commands; Windows variants are packaged separately')
    def test_claude_and_zcode_manifest_commands_execute_sensor(self):
        for host in ('claude', 'zcode'):
            with self.subTest(host=host), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                path = root / 'tasks/fix.md'
                path.parent.mkdir()
                path.write_text(record())
                self.assertEqual('', self.run_hook(host, root, native=True))
                path.write_text(OPEN)
                self.assert_report(host, self.run_hook(host, root, native=True))

    def test_manifests_register_all_tool_sensor_with_correct_entrypoints(self):
        for relative in ('hooks/hooks.json', 'hooks/codex.json', 'hooks/grok.json'):
            data = json.loads((PLUGIN / relative).read_text())
            groups = data['hooks']['PostToolUse']
            self.assertEqual(1, len(groups))
            self.assertNotIn('matcher', groups[0])
            hook = groups[0]['hooks'][0]
            self.assertEqual(10, hook['timeout'])
            if relative == 'hooks/codex.json':
                self.assertNotIn('statusMessage', hook)
                self.assertIn('hooks/post_tool_use.py', hook['command'])
                self.assertIn('post_tool_use.py', hook['commandWindows'])
            else:
                self.assertIn('scripts/lifecycle_hook.py', hook['command'])
        data = json.loads((PLUGIN / 'kimi.plugin.json').read_text())
        hooks = [h for h in data['hooks'] if h['event'] == 'PostToolUse']
        self.assertEqual([], hooks)
        self.assertEqual(['UserPromptSubmit'], [h['event'] for h in data['hooks']])
        self.assertIn('scripts/lifecycle_hook.py', data['hooks'][0]['command'])
        self.assertEqual(10, data['hooks'][0]['timeout'])

    def test_kimi_reports_on_prompt_using_native_session_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / 'tasks/fix.md'
            path.parent.mkdir()
            path.write_text(record())
            binding = root / RUNTIME.session_relative_path('owner')
            binding.parent.mkdir(parents=True)
            binding.write_text('tasks/fix.md\n')
            self.assertIn('Task-state recovery', self.run_hook('kimi', root, 'UserPromptSubmit', selected=False))
            path.write_text(OPEN)
            self.assertEqual('', self.run_hook('kimi', root))
            self.assertEqual('', self.run_hook('kimi', root, 'UserPromptSubmit', selected=False, session='other'))
            report = self.run_hook('kimi', root, 'UserPromptSubmit', selected=False)
            self.assertIn('missing their pair', report)
            self.assertIn(RUNTIME.snapshot_relative_path('tasks/fix.md'), report)
            self.assertLess(report.index('Task-state sensor'), report.index('Task-state recovery'))
            again = self.run_hook('kimi', root, 'UserPromptSubmit', selected=False)
            self.assertNotIn('Task-state sensor', again)
            self.assertIn('Malformed', again)


if __name__ == '__main__':
    unittest.main()
