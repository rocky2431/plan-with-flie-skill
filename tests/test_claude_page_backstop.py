"""Exercise the compacted-page backstop through real hooks and CLI processes."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

from subprocess_environment import clean_environment
from test_session_selection import CLI, PLUGIN, SCRIPTS


def _old_system_python():
    # macOS ships /usr/bin/python3 3.9; hooks run whatever python3 the host finds on PATH.
    candidate = '/usr/bin/python3'
    if not os.path.exists(candidate):
        return None
    probe = subprocess.run([candidate, '-c', 'import sys; print(sys.version_info >= (3, 11))'],
                           capture_output=True, text=True)
    return candidate if probe.returncode == 0 and probe.stdout.strip() == 'False' else None


OLD_PYTHON = _old_system_python()


class PageProcessCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.root = self.base / "project with 'quotes'"
        self.root.mkdir()
        (self.root / '.git').mkdir()
        self.data = self.base / 'plugin-data'
        self.env = clean_environment(CLAUDE_PLUGIN_DATA=str(self.data))
        self.session = 'session-a1234'

    def marker(self, session=None):
        key = hashlib.sha256((session or self.session).encode()).hexdigest()
        return self.data / 'task-state/compacted' / key

    def hook(self, name, *, host='claude', env=None, raw=None, native=False, **fields):
        payload = dict(hook_event_name=name, cwd=str(self.root), session_id=self.session)
        if name == 'SessionStart':
            payload['source'] = 'compact'
        payload.update(fields)
        environment = dict(self.env if env is None else env)
        if native:
            environment[host.upper() + '_PLUGIN_ROOT'] = str(PLUGIN)
            hooks = json.loads((PLUGIN / 'hooks/hooks.json').read_text(encoding='utf-8'))
            command = ['/bin/sh', '-c', hooks['hooks'][name][0]['hooks'][0]['command']]
        else:
            command = [sys.executable, str(SCRIPTS / 'lifecycle_hook.py'), '--host', host]
        result = subprocess.run(command, input=json.dumps(payload) if raw is None else raw,
                                cwd=self.root, env=environment, text=True, capture_output=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual('', result.stderr)
        return result.stdout

    def cli(self, *args, env=None, expected=0):
        result = subprocess.run([sys.executable, str(CLI), *args, '--root', str(self.root)],
                                cwd=self.base, env=self.env if env is None else env,
                                capture_output=True, text=True)
        self.assertEqual(expected, result.returncode, result.stderr)
        return result

    def block(self, **fields):
        output = self.hook('Stop', **fields)
        response = json.loads(output)
        self.assertEqual({'decision', 'reason'}, set(response))
        self.assertEqual('block', response['decision'])
        # Serialized as ASCII before the marker is consumed, so printing cannot fail.
        self.assertEqual(json.dumps(response) + '\n', output)
        commands = [line for line in response['reason'].splitlines() if line.startswith('python3 ')]
        self.assertEqual(2, len(commands))
        prose = '\n'.join(line for line in response['reason'].splitlines() if line not in commands)
        self.assertLessEqual(len(prose), 1200)
        self.assertIn('compacted while no task page was selected', prose)
        self.assertIn('only in the compaction summary', prose)
        self.assertIn('every [unfilled] field, Intent included', prose)
        self.assertIn('UltraGoal goal or another record', prose)
        self.assertIn('exact wording matters', prose)
        self.assertFalse(self.marker(fields.get('session_id')).exists())
        return response['reason'], commands

    def execute(self, command):
        # Printed commands may chain with ' && '; run each part in order, like a shell would.
        for part in command.split(' && '):
            result = subprocess.run(shlex.split(part), cwd=self.base, env=self.env,
                                    text=True, capture_output=True)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual('', result.stderr)
        return result


class ClaudePageBackstopTests(PageProcessCase):
    def test_compact_arms_one_stop_and_second_compact_rearms(self):
        self.assertEqual('', self.hook('Stop'))
        self.assertEqual('', self.hook('SessionStart'))
        self.assertTrue(self.marker().is_file())
        reason, _ = self.block(transcript_path='/transcripts/full conversation.jsonl')
        self.assertIn('/transcripts/full conversation.jsonl', reason)
        self.assertFalse((self.root / '.task-state').exists())
        self.assertEqual('', self.hook('Stop'))
        self.assertEqual('', self.hook('SessionStart'))
        reason, _ = self.block()
        self.assertNotIn('The full conversation is at', reason)
        self.assertEqual('', self.hook('Stop'))

    def test_other_sources_and_events_do_not_arm(self):
        for source in ('startup', 'resume', 'clear', 'other', None, []):
            self.assertEqual('', self.hook('SessionStart', source=source))
            self.assertFalse(self.marker().exists())
        for event in ('PostToolUse', 'UserPromptSubmit', 'SessionEnd'):
            self.assertEqual('', self.hook(event))
            self.assertFalse(self.marker().exists())

    def test_both_printed_commands_execute_as_printed_and_select(self):
        for index in (0, 1):
            with self.subTest(command=index):
                self.cli('deactivate', '--session', self.session)
                self.assertEqual('', self.hook('SessionStart'))
                _, commands = self.block()
                if index == 1:
                    # The printed example is a portable relative path, to be replaced
                    # with the actual existing page's path in a real session.
                    page = self.root / 'path/to/task-page.md'
                    page.parent.mkdir(parents=True)
                    page.write_text('EXISTING-PAGE\n', encoding='utf-8')
                result = self.execute(commands[index])
                if index == 0:
                    slug = datetime.now(UTC).strftime('%Y-%m-%d') + '-' + self.session[:8]
                    self.assertEqual(f'tasks/{slug}.md\n', result.stdout)
                self.assertEqual('', self.hook('Stop'))
                recovered = self.hook('SessionStart')
                self.assertIn('Task-state recovery', recovered)
                self.assertIn('Intent: [unfilled: the confirmed intent]' if index == 0 else 'EXISTING-PAGE', recovered)
                self.assertFalse(self.marker().exists())

    def test_slugs_differ_between_sessions(self):
        slugs = []
        for session in ('first123-abcd', 'second12-abcd'):
            self.assertEqual('', self.hook('SessionStart', session_id=session))
            _, commands = self.block(session_id=session)
            args = shlex.split(commands[0])
            slugs.append(args[args.index('--task') + 1])
        self.assertNotEqual(*slugs)

    def test_all_usable_session_characters_generate_executable_init(self):
        for session in ('UPPER_12-rest', '-_AbC123-rest', '_session-rest', 'x'):
            with self.subTest(session=session):
                self.hook('SessionStart', session_id=session)
                _, commands = self.block(session_id=session)
                self.execute(commands[0])
                self.assertIn('Intent: [unfilled: the confirmed intent]',
                              self.hook('SessionStart', session_id=session))
                self.assertEqual('', self.hook('Stop', session_id=session))

    def test_selected_compaction_then_archive_and_deactivate_does_not_block(self):
        result = self.cli('init', '--task', 'existing', '--objective', 'Keep evidence', '--session', self.session)
        self.assertEqual('tasks/existing.md\n', result.stdout)
        self.assertEqual('', result.stderr)
        for source in ('startup', 'resume', 'clear', 'compact'):
            recovery = self.hook('SessionStart', source=source)
            self.assertIn('Intent: Keep evidence', recovery)
            self.assertIn('tasks/existing.md', recovery)
            self.assertNotIn('## History', recovery)
            self.assertFalse(self.marker().exists())
        archive = self.root / 'tasks/archive/existing.md'
        archive.parent.mkdir()
        (self.root / 'tasks/existing.md').rename(archive)
        self.cli('deactivate', '--session', self.session)
        self.assertEqual('', self.hook('Stop'))

    def test_selecting_after_compaction_consumes_marker_silently(self):
        self.hook('SessionStart')
        self.cli('init', '--file', 'notes/page.md', '--objective', 'Preserve this', '--session', self.session)
        self.assertTrue(self.marker().exists())
        self.assertEqual('', self.hook('Stop'))
        self.assertFalse(self.marker().exists())

    def test_launch_selections_count_but_invalid_or_missing_selections_do_not(self):
        self.cli('init', '--task', 'page', '--objective', 'Selected')
        for pins in ({'TASK_STATE_TASK': 'page'}, {'TASK_STATE_FILE': 'tasks/page.md'}):
            env = dict(self.env, **pins)
            self.assertIn('Intent: Selected', self.hook('SessionStart', env=env))
            self.assertFalse(self.marker().exists())
            self.hook('SessionStart')
            self.assertEqual('', self.hook('Stop', env=env))
            self.assertFalse(self.marker().exists())
        for pins in ({}, {'TASK_STATE_FILE': 'missing.md'}, {'TASK_STATE_FILE': '../outside.md'},
                     {'TASK_STATE_TASK': 'page', 'TASK_STATE_FILE': 'tasks/page.md'}):
            env = dict(self.env, **pins)
            self.hook('SessionStart', env=env)
            self.assertTrue(self.marker().exists())
            self.block(env=env)

    def test_silent_cases_leave_marker_untouched(self):
        variants = [
            ({'stop_hook_active': True}, {}), ({'agent_id': 'worker'}, {}),
            ({'agent_id': None}, {}), ({}, {'TASK_STATE_DISABLED': '1'}),
            ({}, {'CLAUDE_PLUGIN_DATA': ''}),
        ]
        variants += [({'session_id': value}, {}) for value in (None, '', 'bad/id', 'has space', '中', 17, [])]
        for fields, pins in variants:
            with self.subTest(fields=fields, pins=pins):
                marker = self.marker()
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.write_text('untouched', encoding='utf-8')
                env = dict(self.env, **pins)
                for name in ('SessionStart', 'Stop'):
                    self.assertEqual('', self.hook(name, env=env, **fields))
                    self.assertEqual('untouched', marker.read_text(encoding='utf-8'))
                marker.unlink()
                self.assertEqual('', self.hook('SessionStart', env=env, **fields))
                self.assertEqual([], list(marker.parent.iterdir()))
        marker = self.marker()
        marker.write_text('untouched', encoding='utf-8')
        for raw in ('{', 'null', '[]', '"not an event"'):
            self.assertEqual('', self.hook('Stop', raw=raw))
            self.assertEqual('untouched', marker.read_text(encoding='utf-8'))

    def test_filesystem_errors_are_silent_and_do_not_consume_marker(self):
        self.data.mkdir()
        (self.data / 'task-state').write_text('not a directory', encoding='utf-8')
        self.assertEqual('', self.hook('SessionStart'))
        (self.data / 'task-state').unlink()
        self.marker().mkdir(parents=True)
        self.assertEqual('', self.hook('Stop'))
        self.assertTrue(self.marker().is_dir())
        self.marker().rmdir()
        self.marker().write_text('untouched', encoding='utf-8')
        self.assertEqual('', self.hook('Stop', cwd=str(self.root / 'missing')))
        self.assertEqual('untouched', self.marker().read_text(encoding='utf-8'))

    def test_oversized_transcript_path_is_omitted_and_the_block_still_happens(self):
        self.hook('SessionStart')
        reason, _ = self.block(transcript_path='x' * 1200)
        self.assertNotIn('x' * 1200, reason)
        self.assertNotIn('The full conversation is at', reason)
        self.hook('SessionStart')
        reason, _ = self.block(transcript_path='/tmp/t.jsonl')
        self.assertIn('The full conversation is at /tmp/t.jsonl.', reason)

    def test_unencodable_metadata_still_delivers_the_request_once(self):
        self.hook('SessionStart')
        reason, _ = self.block(transcript_path='bad-\ud800')
        self.assertIn('compacted while no task page was selected', reason)
        self.assertEqual('', self.hook('Stop'))

    def test_slug_keeps_the_existing_task_id_rule(self):
        session = 'ABC_DEF9-rest'
        self.assertEqual('', self.hook('SessionStart', session_id=session))
        _, commands = self.block(session_id=session)
        slug = datetime.now(UTC).strftime('%Y-%m-%d') + '-abc-def9'
        self.assertIn(['--task', slug], [shlex.split(commands[0])[i:i + 2] for i in range(len(shlex.split(commands[0])))])
        self.execute(commands[0])
        self.assertTrue((self.root / 'tasks' / f'{slug}.md').is_file())
        rejected = self.cli('init', '--task', 'Upper_Case', '--objective', 'x', expected=2)
        self.assertIn('lowercase', rejected.stderr)

    def test_parallel_stop_processes_block_exactly_once(self):
        self.hook('SessionStart')
        with ThreadPoolExecutor(max_workers=8) as pool:
            outputs = list(pool.map(lambda _: self.hook('Stop'), range(8)))
        self.assertEqual(1, sum(bool(output) for output in outputs), outputs)
        self.assertEqual('block', json.loads(next(output for output in outputs if output))['decision'])

    @unittest.skipIf(os.name == 'nt', 'POSIX shell registration; Windows guards checked separately')
    def test_native_registration_guards_both_hosts(self):
        self.assertEqual('', self.hook('SessionStart', native=True))
        self.assertTrue(self.marker().exists())
        env = dict(self.env, ZCODE_PLUGIN_ROOT=str(PLUGIN), CLAUDE_PLUGIN_ROOT=str(PLUGIN), PATH='')
        self.assertEqual('', self.hook('Stop', native=True, env=env))
        self.assertTrue(self.marker().exists())
        self.assertEqual('block', json.loads(self.hook('Stop', native=True))['decision'])
        self.assertEqual('', self.hook('SessionStart', native=True, host='zcode'))
        self.assertFalse(self.marker().exists())
        self.assertEqual('', self.hook('Stop', host='zcode'))


class InitPageSelectionTests(PageProcessCase):
    def test_init_selects_created_and_existing_task_file_and_legacy_pages(self):
        for selector in ([], ['--task', 'named'], ['--file', 'notes/borrowed.md']):
            with self.subTest(selector=selector):
                for attempt in range(2):
                    result = self.cli('init', *selector, '--objective', 'Intent', '--session', self.session)
                    self.assertEqual('', result.stderr)
                    recovery = self.hook('SessionStart')
                    self.assertIn('Intent: Intent', recovery)
                    self.assertIn(result.stdout.strip(), recovery)
                    self.cli('deactivate', '--session', self.session)

    def test_dangling_and_invalid_bindings_are_replaced_but_activate_stays_strict(self):
        self.cli('init', '--task', 'old', '--objective', 'Old', '--session', self.session)
        binding = self.root / '.task-state/sessions' / (hashlib.sha256(self.session.encode()).hexdigest() + '.ref')
        (self.root / 'tasks/old.md').unlink()
        self.cli('activate', '--task', 'old', '--session', self.session, expected=2)
        for stale in (b'tasks/old.md\n', b'../outside.md\n', b'two\nlines\n', b'\xff'):
            binding.write_bytes(stale)
            result = self.cli('init', '--task', 'new', '--objective', 'New', '--session', self.session)
            self.assertEqual('tasks/new.md\n', result.stdout)
            self.assertEqual('', result.stderr)
            self.assertIn('Intent: New', self.hook('SessionStart'))

    def test_printed_existing_page_command_replaces_a_dangling_selection(self):
        self.cli('init', '--task', 'old', '--objective', 'Old', '--session', self.session)
        (self.root / 'tasks/archive').mkdir()
        (self.root / 'tasks/old.md').rename(self.root / 'tasks/archive/old.md')
        page = self.root / 'path/to/task-page.md'
        page.parent.mkdir(parents=True)
        page.write_text('EXISTING-PAGE\n', encoding='utf-8')
        # Recovery reports the unreadable selection as in 0.8.0; the backstop still arms.
        self.assertIn('Recovery skipped', self.hook('SessionStart'))
        self.assertTrue(self.marker().exists())
        _, commands = self.block()
        self.execute(commands[1])
        self.assertIn('EXISTING-PAGE', self.hook('SessionStart', source='startup'))
        self.assertEqual('', self.hook('Stop'))

    def test_empty_session_is_rejected_before_any_record_is_written(self):
        for value in ('', '   '):
            result = self.cli('init', '--task', 'blank', '--objective', 'Blank', '--session', value, expected=2)
            self.assertEqual('', result.stdout)
            self.assertFalse((self.root / 'tasks/blank.md').exists())

    @unittest.skipUnless(OLD_PYTHON, 'needs a python3 older than 3.11 at /usr/bin/python3')
    def test_hooks_run_on_the_oldest_system_python(self):
        self.cli('init', '--task', 'page', '--objective', 'Old interpreter', '--session', self.session)
        for event in ({'hook_event_name': 'SessionStart', 'source': 'compact'},
                      {'hook_event_name': 'Stop'}):
            payload = dict(event, cwd=str(self.root), session_id=self.session)
            result = subprocess.run([OLD_PYTHON, str(SCRIPTS / 'lifecycle_hook.py'), '--host', 'claude'],
                                    input=json.dumps(payload), cwd=self.root, env=self.env,
                                    text=True, capture_output=True)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual('', result.stderr)
        self.cli('deactivate', '--session', self.session)
        self.hook('SessionStart')
        result = subprocess.run([OLD_PYTHON, str(SCRIPTS / 'lifecycle_hook.py'), '--host', 'claude'],
                                input=json.dumps({'hook_event_name': 'Stop', 'cwd': str(self.root),
                                                  'session_id': self.session}),
                                cwd=self.root, env=self.env, text=True, capture_output=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual('block', json.loads(result.stdout)['decision'])

    @unittest.skipIf(os.name == 'nt', 'Symlink creation needs privileges on Windows')
    def test_init_replaces_an_invalid_binding_symlink_without_touching_its_target(self):
        self.cli('init', '--task', 'page', '--objective', 'Page', '--session', self.session)
        binding = self.root / '.task-state/sessions' / (hashlib.sha256(self.session.encode()).hexdigest() + '.ref')
        target = self.base / 'outside.ref'
        target.write_text('untouched', encoding='utf-8')
        binding.unlink()
        binding.symlink_to(target)
        self.cli('activate', '--task', 'page', '--session', self.session, expected=2)
        result = self.cli('init', '--task', 'page', '--objective', 'Ignored', '--session', self.session)
        self.assertEqual('tasks/page.md\n', result.stdout)
        self.assertEqual('', result.stderr)
        self.assertFalse(binding.is_symlink())
        self.assertEqual('untouched', target.read_text(encoding='utf-8'))
        self.assertIn('Intent: Page', self.hook('SessionStart'))

    def test_legacy_record_and_dangling_legacy_binding_are_supported(self):
        page = self.root / '.tasks/legacy.md'
        page.parent.mkdir()
        page.write_text('LEGACY-PAGE\n', encoding='utf-8')
        result = self.cli('init', '--task', 'legacy', '--objective', 'Ignored', '--session', self.session)
        self.assertEqual('.tasks/legacy.md\n', result.stdout)
        self.assertIn('LEGACY-PAGE', self.hook('SessionStart'))
        self.cli('deactivate', '--session', self.session)
        binding = self.root / '.tasks/.sessions' / (hashlib.sha256(self.session.encode()).hexdigest() + '.ref')
        binding.parent.mkdir()
        binding.write_text('missing.md\n', encoding='utf-8')
        result = self.cli('init', '--task', 'legacy', '--objective', 'Ignored', '--session', self.session)
        self.assertEqual('.tasks/legacy.md\n', result.stdout)
        self.assertFalse(binding.exists())
        self.assertIn('LEGACY-PAGE', self.hook('SessionStart'))

    def test_init_keeps_another_found_selection_and_prints_executable_switch_commands(self):
        self.cli('init', '--task', 'old', '--objective', 'Old', '--session', self.session)
        result = self.cli('init', '--file', 'notes/new page.md', '--objective', 'New', '--session', self.session)
        self.assertEqual('notes/new page.md\n', result.stdout)
        self.assertEqual(1, len(result.stderr.splitlines()))
        self.assertIn('tasks/old.md', result.stderr)
        self.assertIn('Intent: Old', self.hook('SessionStart'))
        self.cli('activate', '--file', 'notes/new page.md', '--session', self.session, expected=2)
        commands = result.stderr.split('run ', 1)[1].strip().split(' && ')
        self.assertEqual(2, len(commands))
        self.execute(commands[0])
        # activate prints the binding path, but no stderr.
        self.execute(commands[1])
        self.assertIn('Intent: New', self.hook('SessionStart'))

    def test_session_environment_is_not_a_default_for_any_command(self):
        env = dict(self.env, CLAUDE_CODE_SESSION_ID=self.session)
        result = self.cli('init', '--task', 'unbound', '--objective', 'Unbound', env=env)
        self.assertEqual('tasks/unbound.md\n', result.stdout)
        self.assertEqual([], list((self.root / '.task-state/sessions').iterdir()))
        self.cli('activate', '--task', 'unbound', env=env, expected=2)
        self.cli('deactivate', env=env, expected=2)

    def test_template_fields_and_guidance_are_exact(self):
        result = self.cli('init', '--task', 'template', '--objective', 'Confirmed intent with authority')
        text = (self.root / result.stdout.strip()).read_text(encoding='utf-8')
        before, current = text.split('<!-- current-state -->\n')
        content, history = current.split('<!-- /current-state -->')
        self.assertIn('<!-- Keep the current-state block true and short. Append to History; do not rewrite earlier entries. -->', before)
        self.assertEqual([
            'Intent: Confirmed intent with authority',
            'Conclusions in force: [unfilled: each conclusion with its evidence: file, command output, or the transcript path and what to find there]',
            'Done, do not redo: [unfilled: each completed result with its evidence]',
            'Next: [unfilled]', 'Open owner decisions: [unfilled]',
        ], content.splitlines())
        self.assertEqual('\n\n## History\n', history)


if __name__ == '__main__':
    unittest.main()
