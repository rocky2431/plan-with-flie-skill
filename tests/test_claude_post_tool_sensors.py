"""Drive Claude's advisory reminders through real hook and CLI processes."""

from __future__ import annotations

import concurrent.futures
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_current_state import CLOSE, OPEN, RUNTIME, record
from test_session_selection import PLUGIN, SCRIPTS


class ClaudePostToolSensorsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        (self.root / '.git').mkdir()
        self.path = self.root / 'notes/current task.md'
        self.path.parent.mkdir()
        self.path.write_text(record(), encoding='utf-8')
        self.transcript = self.root / 'session.jsonl'
        self.data = self.root / 'plugin-data'
        self.data.mkdir()
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith('TASK_STATE_') and not k.endswith('PLUGIN_DATA')}
        self.env['CLAUDE_PLUGIN_DATA'] = str(self.data)

    def assistant(self, size):
        return {'type': 'assistant', 'message': {'usage': {
            'input_tokens': 100, 'cache_read_input_tokens': size - 150,
            'cache_creation_input_tokens': 50}}}

    def usage(self, size):
        # Later non-assistant entries must not obscure the last assistant usage.
        entries = [self.assistant(900_000), self.assistant(size), {'type': 'user'}]
        self.transcript.write_text(''.join(json.dumps(e) + '\n' for e in entries), encoding='utf-8')

    def hook(self, *, selected=True, host='claude', event=None, env=None, raw=None):
        environment = dict(self.env)
        if selected:
            environment.update(TASK_STATE_FILE='notes/current task.md', TASK_STATE_ROOT=str(self.root))
        environment.update(env or {})
        payload = {'hook_event_name': 'PostToolUse', 'cwd': str(self.root),
                   'session_id': 'owner', 'sessionId': 'owner', 'tool_name': 'Read',
                   'transcript_path': str(self.transcript)}
        payload.update(event or {})
        if host == 'codex':
            command = [sys.executable, str(PLUGIN / 'hooks/post_tool_use.py')]
        else:
            command = [sys.executable, str(SCRIPTS / 'lifecycle_hook.py'), '--host', host]
        result = subprocess.run(command, input=raw if raw is not None else json.dumps(payload),
                                env=environment, capture_output=True, text=True, timeout=10)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual('', result.stderr)
        if not result.stdout:
            return ''
        output = json.loads(result.stdout)
        self.assertEqual({'hookSpecificOutput'}, set(output))
        detail = output['hookSpecificOutput']
        self.assertEqual({'hookEventName', 'additionalContext'}, set(detail))
        self.assertEqual(payload['hook_event_name'], detail['hookEventName'])
        return detail['additionalContext']

    def write_event(self, **extra):
        return {'tool_name': 'Write', 'tool_input': {'file_path': str(self.path)}, **extra}

    def assert_reminder(self, context):
        self.assertIn('notes/current task.md', context)
        self.assertLessEqual(len(context), 800)
        self.assertTrue(context.endswith('Nothing was blocked.'))

    def test_growth_threshold_once_edit_and_drop_reset_baseline(self):
        original = self.path.read_bytes()
        self.usage(20_000)
        self.assertEqual('', self.hook())
        self.usage(119_999)
        self.assertEqual('', self.hook())
        self.usage(120_000)
        context = self.hook()
        self.assert_reminder(context)
        self.assertIn('100,000 tokens', context)
        for phrase in ("owner's wording", 'decisions', 'corrections', 'evidence',
                       'progress', 'next step', 'current-state block', 'History',
                       'Compaction may happen at any time'):
            self.assertIn(phrase, context)
        self.usage(300_000)
        self.assertEqual('', self.hook())
        self.assertEqual(original, self.path.read_bytes())
        self.path.write_text(record('Next: integrate.\n'), encoding='utf-8')
        self.assertEqual('', self.hook())
        self.usage(399_999)
        self.assertEqual('', self.hook())
        self.usage(401_000)
        self.assert_reminder(self.hook())
        self.assertEqual('', self.hook())
        self.usage(10_000)
        self.assertEqual('', self.hook())
        self.usage(109_999)
        self.assertEqual('', self.hook())
        self.usage(110_000)
        self.assert_reminder(self.hook())

    def test_drop_resets_even_before_an_episode_is_reported(self):
        self.usage(200_000)
        self.assertEqual('', self.hook())
        self.usage(150_000)
        self.assertEqual('', self.hook())
        self.usage(250_000)
        self.assert_reminder(self.hook())

    def test_growth_uses_native_binding_and_is_per_session(self):
        binding = self.root / RUNTIME.session_relative_path('owner')
        binding.parent.mkdir(parents=True, exist_ok=True)
        binding.write_text('notes/current task.md\n', encoding='utf-8')
        self.usage(20_000)
        self.assertEqual('', self.hook(selected=False))
        self.usage(120_000)
        self.assertEqual('', self.hook(event={'session_id': 'other'}))
        self.assert_reminder(self.hook(selected=False))
        self.usage(220_000)
        self.assert_reminder(self.hook(event={'session_id': 'other'}))
        self.assertEqual('', self.hook(selected=False))

    def test_growth_resets_when_switching_to_same_text_in_another_record(self):
        self.usage(20_000)
        self.assertEqual('', self.hook())
        other = self.root / 'notes/other.md'
        other.write_text(record(), encoding='utf-8')
        self.usage(120_000)
        self.assertEqual('', self.hook(env={'TASK_STATE_FILE': 'notes/other.md'}))
        self.usage(220_000)
        self.assertIn('notes/other.md', self.hook(env={'TASK_STATE_FILE': 'notes/other.md'}))

    def test_agent_events_and_disabled_calls_do_not_consume_growth_episode(self):
        self.usage(20_000)
        self.assertEqual('', self.hook())
        self.usage(120_000)
        for event in ({'agent_id': 'worker'}, {'agent_id': None}):
            self.assertEqual('', self.hook(event=event))
        self.assertEqual('', self.hook(env={'TASK_STATE_DISABLED': '1'}))
        self.assert_reminder(self.hook())

    def test_non_claude_hosts_do_not_run_growth_sensor(self):
        self.usage(20_000)
        self.assertEqual('', self.hook())
        self.usage(120_000)
        for host in ('zcode', 'kimi', 'grok', 'codex'):
            with self.subTest(host=host):
                context = self.hook(host=host, env={'GROK_PLUGIN_DATA': str(self.data)})
                self.assertNotIn('Task-state context growth', context)
                self.assertNotIn('Task-state selection', context)
        self.assert_reminder(self.hook())

    def test_missing_garbage_and_usage_free_transcripts_are_silent(self):
        self.assertEqual('', self.hook())
        fixtures = [b'', b'garbage\n', b'\xff\n', b'[]\n', b'{"type":"user"}\n',
                    b'{"type":"assistant","message":{}}\n',
                    b'{"type":"assistant","message":{"usage":{}}}\n']
        for fixture in fixtures:
            with self.subTest(fixture=fixture):
                self.transcript.write_bytes(fixture)
                self.assertEqual('', self.hook())
        # Never use older usage when the last assistant message has none.
        self.transcript.write_text(json.dumps(self.assistant(200_000)) + '\n' +
                                   '{"type":"assistant","message":{}}\n', encoding='utf-8')
        self.assertEqual('', self.hook())
        self.assertFalse((self.root / '.task-state/context-growth').exists())

    def test_invalid_usage_fields_and_transcript_paths_fail_open(self):
        for value in (-1, 1.5, True, '100000', None):
            entry = self.assistant(120_000)
            entry['message']['usage']['input_tokens'] = value
            self.transcript.write_text(json.dumps(entry) + '\n', encoding='utf-8')
            self.assertEqual('', self.hook())
        for path in (str(self.root), [], {}, None, 3):
            self.assertEqual('', self.hook(event={'transcript_path': path}))
        self.path.write_bytes(b'\xff')
        self.usage(120_000)
        self.assertEqual('', self.hook())

    def test_malformed_events_fail_open(self):
        for raw in ('{', '[]', 'null', '"text"'):
            self.assertEqual('', self.hook(raw=raw))
        self.usage(120_000)
        for session in (None, [], {}, '', ' '):
            self.assertEqual('', self.hook(event={'session_id': session}))

    def test_fifty_megabyte_transcript_and_deterministic_read_bound(self):
        self.usage(20_000)
        self.assertEqual('', self.hook())
        with self.transcript.open('wb') as handle:
            chunk = b'x' * (1024 * 1024 - 1) + b'\n'
            for _ in range(50):
                handle.write(chunk)
            handle.write((json.dumps(self.assistant(120_000)) + '\n').encode())
        self.assertGreaterEqual(self.transcript.stat().st_size, 50 * 1024 * 1024)
        self.assert_reminder(self.hook())

        # Enforce the I/O contract deterministically, without a timing assumption.
        spec = importlib.util.spec_from_file_location('claude_sensors', SCRIPTS / 'claude_post_tool_sensors.py')
        module = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(SCRIPTS))
        try:
            spec.loader.exec_module(module)
        finally:
            sys.path.pop(0)
        real_open = Path.open
        reads = []

        class BoundedReader:
            def __init__(self, handle):
                self.handle = handle

            def __enter__(self):
                self.handle.__enter__()
                return self

            def __exit__(self, *args):
                return self.handle.__exit__(*args)

            def seek(self, *args):
                return self.handle.seek(*args)

            def tell(self):
                return self.handle.tell()

            def read(self, size=-1):
                if size < 0 or size > module.TRANSCRIPT_TAIL_BYTES:
                    raise AssertionError('Unbounded transcript read')
                result = self.handle.read(size)
                reads.append(len(result))
                return result

        def bounded_open(path, *args, **kwargs):
            handle = real_open(path, *args, **kwargs)
            return BoundedReader(handle) if path == self.transcript else handle

        with patch.object(Path, 'open', bounded_open):
            self.assertEqual(120_000, module.transcript_context_size(self.transcript))
        self.assertTrue(reads)
        self.assertLessEqual(sum(reads), module.TRANSCRIPT_TAIL_BYTES)

    def test_unreadable_transcript_and_corrupt_sensor_state_fail_open(self):
        self.usage(20_000)
        self.transcript.chmod(0)
        try:
            if not os.access(self.transcript, os.R_OK):
                self.assertEqual('', self.hook())
        finally:
            self.transcript.chmod(0o600)
        self.assertEqual('', self.hook())
        state = next((self.root / '.task-state/context-growth').glob('*.json'))
        state.write_text('not JSON', encoding='utf-8')
        self.usage(120_000)
        self.assertEqual('', self.hook())
        self.assertEqual(record(), self.path.read_text(encoding='utf-8'))

    def test_tail_without_complete_assistant_line_stays_silent(self):
        self.usage(20_000)
        self.assertEqual('', self.hook())
        self.transcript.write_text(json.dumps(self.assistant(120_000)) + '\n' +
                                   'x' * (2 * 1024 * 1024), encoding='utf-8')
        self.assertEqual('', self.hook())

    def test_damage_and_growth_report_share_one_payload(self):
        # A still-malformed record can accumulate context; the damage check is
        # independent of the growth baseline and must retain its own report.
        self.path.write_text(OPEN + '\nbroken\n', encoding='utf-8')
        self.usage(20_000)
        self.assertIn('missing their pair', self.hook())
        self.path.write_text(record(), encoding='utf-8')
        self.assertEqual('', self.hook())
        self.path.write_text(OPEN + '\nbroken again\n', encoding='utf-8')
        self.assertIn('missing their pair', self.hook())
        # Removing the snapshot observation forces a fresh damage report without
        # changing the record text or its context-growth episode.
        snapshot = self.root / RUNTIME.snapshot_relative_path('notes/current task.md')
        for path in snapshot.parent.iterdir():
            path.unlink()
        self.usage(120_000)
        context = self.hook()
        self.assertIn('missing their pair', context)
        self.assertIn('Task-state context growth', context)
        self.assertTrue(context.endswith('Nothing was blocked.'))
        self.assertEqual('', self.hook())

    def test_growth_report_is_claimed_once_for_parallel_hooks(self):
        self.usage(20_000)
        self.assertEqual('', self.hook())
        self.usage(120_000)
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda _: self.hook(), range(6)))
        self.assertEqual(1, sum(bool(result) for result in results))

    def test_unselected_write_reports_once_and_printed_command_selects_and_recovers(self):
        context = self.hook(selected=False, event=self.write_event())
        self.assert_reminder(context)
        self.assertIn('no selected record', context)
        self.assertIn('different task', context)
        self.assertFalse((self.root / '.task-state').exists())
        self.assertEqual('', self.hook(selected=False, event=self.write_event()))
        command = context.split('To select it, run:\n', 1)[1].split('\n', 1)[0]
        args = shlex.split(command)
        self.assertEqual(str((SCRIPTS / 'task_state.py').resolve()), args[1])
        result = subprocess.run(args, cwd=self.root, env=self.env, capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)
        binding = self.root / RUNTIME.session_relative_path('owner')
        self.assertEqual('notes/current task.md\n', binding.read_text(encoding='utf-8'))
        self.assertEqual('', self.hook(selected=False, event=self.write_event()))
        context = self.hook(selected=False, event={'hook_event_name': 'SessionStart', 'source': 'compact'})
        self.assertIn('Task-state recovery data', context)
        self.assertIn('Next: verify.', context)

    def test_each_write_tool_and_session_file_pair_is_reported_once(self):
        for index, tool in enumerate(('Write', 'Edit', 'MultiEdit')):
            event = self.write_event(tool_name=tool, session_id=f'owner-{index}')
            self.assert_reminder(self.hook(selected=False, event=event))
            self.assertEqual('', self.hook(selected=False, event=event))
        other = self.root / 'notes/another.md'
        other.write_text(record(), encoding='utf-8')
        event = self.write_event(tool_input={'file_path': str(other)})
        self.assertIn('notes/another.md', self.hook(selected=False, event=event))
        self.assert_reminder(self.hook(selected=False, event=self.write_event()))

    def test_unselected_is_silent_for_existing_or_invalid_launch_selection(self):
        for env in ({'TASK_STATE_FILE': 'notes/current task.md'},
                    {'TASK_STATE_TASK': 'missing'}, {'TASK_STATE_FILE': 'missing.md'},
                    {'TASK_STATE_FILE': '', 'TASK_STATE_TASK': 'missing'}):
            self.assertEqual('', self.hook(selected=False, event=self.write_event(), env=env))
        binding = self.root / RUNTIME.session_relative_path('owner')
        binding.parent.mkdir(parents=True, exist_ok=True)
        for value in ('notes/current task.md\n', 'missing.md\n', '../outside.md\n'):
            binding.write_text(value, encoding='utf-8')
            self.assertEqual('', self.hook(selected=False, event=self.write_event()))
        self.assertFalse((self.data / 'task-state').exists())

    def test_unselected_ignores_non_records_and_invalid_tool_inputs(self):
        for text in ('# ordinary', OPEN, CLOSE + '\n' + OPEN, record() + record(),
                     f'```markdown\n{record()}\n```\n'):
            self.path.write_text(text, encoding='utf-8')
            self.assertEqual('', self.hook(selected=False, event=self.write_event()))
        self.path.write_bytes(b'\xff')
        self.assertEqual('', self.hook(selected=False, event=self.write_event()))
        self.path.unlink()
        self.assertEqual('', self.hook(selected=False, event=self.write_event()))
        for tool_input in (None, [], {}, {'file_path': []}, {'file_path': str(self.root)}):
            self.assertEqual('', self.hook(selected=False, event=self.write_event(tool_input=tool_input)))
        self.assertFalse((self.root / '.task-state').exists())

    def test_unselected_ignores_other_tools_hosts_subagents_and_disabled_calls(self):
        for tool in ('Read', 'Bash', 'apply_patch'):
            self.assertEqual('', self.hook(selected=False, event=self.write_event(tool_name=tool)))
        for host in ('zcode', 'kimi', 'codex', 'grok'):
            self.assertEqual('', self.hook(selected=False, host=host, event=self.write_event(),
                                           env={'GROK_PLUGIN_DATA': str(self.data)}))
        for event in (self.write_event(agent_id='worker'), self.write_event(agent_id=None)):
            self.assertEqual('', self.hook(selected=False, event=event))
        self.assertEqual('', self.hook(selected=False, event=self.write_event(),
                                       env={'TASK_STATE_DISABLED': '1'}))
        self.assertFalse((self.root / '.task-state').exists())
        self.assert_reminder(self.hook(selected=False, event=self.write_event()))

    def test_unselected_requires_available_plugin_data(self):
        del self.env['CLAUDE_PLUGIN_DATA']
        self.assertEqual('', self.hook(selected=False, event=self.write_event()))
        for data in ('', str(self.root / 'missing-data'), str(self.path)):
            self.assertEqual('', self.hook(selected=False, event=self.write_event(),
                                           env={'CLAUDE_PLUGIN_DATA': data}))
        self.assertFalse((self.root / '.task-state').exists())

    def test_unselected_uses_cli_root_discovery_and_rejects_outside_file(self):
        nested = self.root / 'src/nested'
        nested.mkdir(parents=True)
        event = self.write_event(cwd=str(nested), tool_input={'file_path': '../../notes/current task.md'})
        context = self.hook(selected=False, event=event)
        self.assert_reminder(context)
        args = shlex.split(context.split('To select it, run:\n')[1].split('\n')[0])
        self.assertEqual(str(self.root), args[args.index('--root') + 1])
        outside = self.root / 'outside.md'
        outside.write_text(record(), encoding='utf-8')
        # A nearer Git boundary must not be bypassed to suggest an outer file.
        (nested / '.git').mkdir()
        self.assertEqual('', self.hook(selected=False, event=self.write_event(
            cwd=str(nested), tool_input={'file_path': str(outside)})))

    def test_unselected_honors_root_pin_for_non_git_workspace(self):
        (self.root / '.git').rmdir()
        subdir = self.root / 'src'
        subdir.mkdir()
        event = self.write_event(cwd=str(subdir))
        context = self.hook(selected=False, event=event, env={'TASK_STATE_ROOT': str(self.root)})
        self.assert_reminder(context)
        args = shlex.split(context.split('To select it, run:\n')[1].split('\n')[0])
        self.assertEqual(str(self.root), args[args.index('--root') + 1])

    def test_unselected_claim_is_atomic_for_parallel_hooks(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda _: self.hook(selected=False, event=self.write_event()), range(6)))
        self.assertEqual(1, sum(bool(result) for result in results))
        self.assertFalse((self.root / '.task-state').exists())

    def test_synthetic_and_zero_usage_lines_preserve_real_growth_baseline(self):
        self.usage(300_000)
        self.assertEqual('', self.hook())
        state_path = next((self.root / '.task-state/context-growth').glob('*.json'))
        initial_state = state_path.read_bytes()
        for model, size in (('<synthetic>', 0), ('real-model', 0), ('<synthetic>', 500_000)):
            with self.subTest(model=model, size=size):
                entry = {'type': 'assistant', 'message': {'model': model, 'usage': {
                    'input_tokens': size, 'cache_read_input_tokens': 0,
                    'cache_creation_input_tokens': 0}}}
                with self.transcript.open('a', encoding='utf-8') as handle:
                    handle.write(json.dumps(entry) + '\n')
                self.assertEqual('', self.hook())
                self.assertEqual(initial_state, state_path.read_bytes())
                self.assertEqual(300_000, json.loads(state_path.read_text(encoding='utf-8'))['baseline'])
        with self.transcript.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(self.assistant(310_000)) + '\n')
        self.assertEqual('', self.hook())
        self.assertEqual(initial_state, state_path.read_bytes())
        with self.transcript.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(self.assistant(410_000)) + '\n')
        context = self.hook()
        self.assert_reminder(context)
        self.assertIn('110,000 tokens', context)
        state = json.loads(state_path.read_text(encoding='utf-8'))
        self.assertEqual(300_000, state['baseline'])
        self.assertIs(True, state['reported'])
        self.assertEqual('', self.hook())

    def test_synthetic_only_tail_does_not_create_or_change_growth_state(self):
        synthetic = {'type': 'assistant', 'message': {'model': '<synthetic>', 'usage': {
            'input_tokens': 0, 'cache_read_input_tokens': 0, 'cache_creation_input_tokens': 0}}}
        synthetic_lines = json.dumps(synthetic) + '\n' + json.dumps(synthetic) + '\n'
        self.transcript.write_text(synthetic_lines, encoding='utf-8')
        self.assertEqual('', self.hook())
        self.assertFalse((self.root / '.task-state/context-growth').exists())
        self.usage(300_000)
        self.assertEqual('', self.hook())
        state_path = next((self.root / '.task-state/context-growth').glob('*.json'))
        initial_state = state_path.read_bytes()
        # The earlier real usage is outside the bounded tail and must not be used.
        self.transcript.write_text(json.dumps(self.assistant(600_000)) + '\n' +
                                   'x' * (1024 * 1024) + '\n' + synthetic_lines, encoding='utf-8')
        self.assertEqual('', self.hook())
        self.assertEqual(initial_state, state_path.read_bytes())

    def long_record(self, length):
        suffix = " record's.md"
        parts = ['notes']
        remaining = length - len('notes/') - len(suffix)
        while remaining > 120:
            parts.append('d' * 100)
            remaining -= 101
        parts.append('f' * remaining + suffix)
        relative = '/'.join(parts)
        self.assertEqual(length, len(relative))
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(record(), encoding='utf-8')
        return relative, path

    def test_long_unselected_paths_report_once_and_printed_commands_recover(self):
        for index, length in enumerate((166, 400), start=1):
            with self.subTest(length=length):
                relative, path = self.long_record(length)
                session = f'owner-{length}'
                event = self.write_event(session_id=session, tool_input={'file_path': str(path)})
                context = self.hook(selected=False, event=event)
                self.assertEqual('Task-state selection: ' + relative[:147] + '...', context.split('\n')[0])
                self.assertTrue(context.endswith('Nothing was blocked.'))
                command = context.split('To select it, run:\n', 1)[1].split('\n', 1)[0]
                report_text = context.replace(command + '\n', '', 1)
                self.assertLessEqual(len(report_text), 800)
                self.assertNotIn(relative, report_text)
                args = shlex.split(command)
                self.assertEqual(str((SCRIPTS / 'task_state.py').resolve()), args[1])
                self.assertIn('--file=' + relative, args)
                self.assertIn('--session=' + session, args)
                self.assertEqual(str(self.root), args[args.index('--root') + 1])
                self.assertEqual(length == 166, not (self.root / '.task-state').exists())
                self.assertEqual(index, len(list((self.data / 'task-state/unselected').glob('*.sent'))))
                self.assertEqual('', self.hook(selected=False, event=event))
                result = subprocess.run(command, shell=True, cwd=self.root, env=self.env,
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual('', result.stderr)
                binding = self.root / RUNTIME.session_relative_path(session)
                self.assertEqual(relative + '\n', binding.read_text(encoding='utf-8'))
                self.assertEqual('', self.hook(selected=False, event=event))
                context = self.hook(selected=False, event={
                    'hook_event_name': 'SessionStart', 'source': 'compact', 'session_id': session})
                self.assertIn('Task-state recovery data', context)
                self.assertIn('Next: verify.', context)

    def test_printed_command_selects_dash_leading_file_and_session(self):
        dashed = self.root / '-record.md'
        dashed.write_text(record(), encoding='utf-8')
        event = self.write_event(session_id='-owner', tool_input={'file_path': str(dashed)})
        context = self.hook(selected=False, event=event)
        self.assertIn('Task-state selection: -record.md', context)
        command = context.split('To select it, run:\n', 1)[1].split('\n', 1)[0]
        result = subprocess.run(shlex.split(command), cwd=self.root, env=self.env,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(0, result.returncode, result.stderr)
        binding = self.root / RUNTIME.session_relative_path('-owner')
        self.assertEqual('-record.md\n', binding.read_text(encoding='utf-8'))
        context = self.hook(selected=False, event={
            'hook_event_name': 'SessionStart', 'source': 'compact', 'session_id': '-owner'})
        self.assertIn('Task-state recovery data', context)

    def test_growth_after_context_drop_does_not_claim_a_record_change(self):
        original = self.path.read_bytes()
        self.usage(20_000)
        self.assertEqual('', self.hook())
        self.usage(120_000)
        self.assert_reminder(self.hook())
        self.usage(10_000)
        self.assertEqual('', self.hook())
        self.usage(110_000)
        context = self.hook()
        self.assert_reminder(context)
        self.assertIn('100,000 tokens', context)
        self.assertNotIn('last observed changing', context)
        self.assertIn('context last shrank', context)
        self.assertEqual(original, self.path.read_bytes())

    def test_long_selected_path_reports_growth_once_and_marks_episode(self):
        relative, _ = self.long_record(467)
        env = {'TASK_STATE_FILE': relative}
        self.usage(300_000)
        self.assertEqual('', self.hook(env=env))
        self.usage(400_000)
        context = self.hook(env=env)
        self.assertEqual('Task-state context growth: ' + relative[:147] + '...', context.split('\n')[0])
        self.assertIn('100,000 tokens', context)
        self.assertLessEqual(len(context), 800)
        self.assertTrue(context.endswith('Nothing was blocked.'))
        state_path = next((self.root / '.task-state/context-growth').glob('*.json'))
        state = json.loads(state_path.read_text(encoding='utf-8'))
        self.assertEqual(relative, state['record'])
        self.assertEqual(300_000, state['baseline'])
        self.assertIs(True, state['reported'])
        self.assertEqual('', self.hook(env=env))


if __name__ == '__main__':
    unittest.main()
