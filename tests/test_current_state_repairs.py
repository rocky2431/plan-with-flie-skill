"""Regressions for observation baselines, recovery copies and host delivery."""

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from test_current_state import CLI_PATH, CLOSE, OPEN, RUNTIME, record
import test_post_tool_sensor as host_tests


class ObservationRepairTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.path = self.root / 'tasks/fix.md'
        self.path.parent.mkdir()
        self.good = record()
        self.path.write_text(self.good, encoding='utf-8')
        self.copy = self.root / RUNTIME.snapshot_relative_path('tasks/fix.md')
        self.seen = self.copy.with_suffix('.seen')
        self.absolute = self.copy.with_suffix('.abs')
        self.environment = patch.dict(os.environ, {'TASK_STATE_DISABLED': '0'})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def sense(self, text=None):
        if text is not None:
            self.path.write_text(text, encoding='utf-8')
        return RUNTIME.sense_selected_record(self.root, state_file='tasks/fix.md')

    def copies(self):
        return [p.read_text(encoding='utf-8') if p.exists() else None for p in
                (self.copy, self.copy.with_suffix('.1.md'), self.copy.with_suffix('.2.md'))]

    def test_structure_changes_are_ignored_and_intended_history_change_rebases(self):
        initial = self.good + '<!-- Old template guidance. -->\n'
        self.assertIsNone(self.sense(initial))
        translated = initial.replace('## History', '  ## 历史').replace(
            '<!-- Old template guidance. -->', ' <!-- Replacement guidance. -->')
        self.assertIsNone(self.sense(translated))
        intended = translated.replace('- first\n', '- revised deliberately\n')
        self.assertIn('earlier history entry', self.sense(intended))
        self.assertEqual(translated, self.copy.read_text(encoding='utf-8'))
        for i in range(6):
            intended = intended.replace('Next:', f'Next {i}:', 1) + f'- verified {i}\n'
            self.assertIsNone(self.sense(intended))
            self.assertEqual(intended, self.copy.read_text(encoding='utf-8'))
        self.assertIn('earlier history entry', self.sense(intended.replace('- second\n', '')))

    def test_persistent_absolute_damage_reports_once_and_preserves_copy(self):
        self.assertIsNone(self.sense())
        broken = OPEN + '\nmissing close'
        self.assertIn('missing their pair', self.sense(broken))
        for i in range(6):
            self.assertIsNone(self.sense(broken + f'\nedit {i}'))
            self.assertEqual(self.good, self.copy.read_text(encoding='utf-8'))
        self.assertEqual(broken + '\nedit 5', self.seen.read_text(encoding='utf-8'))
        oversize = record('中' * 3001 + '\n')
        self.assertIn('3002 characters', self.sense(oversize))
        self.assertIsNone(self.sense(oversize + '<!-- later edit -->\n'))
        self.assertIsNone(self.sense(self.good))
        self.assertFalse(self.absolute.exists())
        self.assertEqual([], list(self.copy.parent.glob(self.copy.stem + '.report.*')))

    def test_three_generations_rotate_only_on_distinct_passing_text(self):
        self.assertIsNone(self.sense())
        quiet_damage = record('Progress: an incorrect claim that keeps structure.\n')
        self.assertIsNone(self.sense(quiet_damage))
        self.assertEqual([quiet_damage, self.good, None], self.copies())
        for i in range(3):
            self.assertIsNone(self.sense())
            self.assertEqual([quiet_damage, self.good, None], self.copies())
        versions = [record(f'Next: pass {i}.\n') for i in range(3)]
        for i, version in enumerate(versions):
            self.assertIsNone(self.sense(version))
            expected = ([version, quiet_damage, self.good] if i == 0 else
                        [version, versions[0], quiet_damage] if i == 1 else
                        [version, versions[1], versions[0]])
            self.assertEqual(expected, self.copies())
        report = self.sense(OPEN)
        for path in (self.copy, self.copy.with_suffix('.1.md'), self.copy.with_suffix('.2.md')):
            self.assertIn(path.relative_to(self.root).as_posix(), report)
        positions = [report.index(p.name) for p in
                     (self.copy, self.copy.with_suffix('.1.md'), self.copy.with_suffix('.2.md'))]
        self.assertEqual(sorted(positions), positions)
        self.assertLessEqual(len(report), 800)

    def test_unchanged_observation_does_not_make_directories_or_write(self):
        self.assertIsNone(self.sense())
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.copy.parent.iterdir()}
        with patch.object(Path, 'mkdir', side_effect=AssertionError('unchanged mkdir')) as mkdir, \
                patch.object(RUNTIME, 'atomic_write', side_effect=AssertionError('unchanged write')) as write:
            self.assertIsNone(self.sense())
        mkdir.assert_not_called()
        write.assert_not_called()
        self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_mtime_ns)
                                  for p in self.copy.parent.iterdir()})

    def test_unreadable_baselines_fall_back_or_check_without_baseline(self):
        self.assertIsNone(self.sense())
        self.seen.write_bytes(b'\xff')
        self.assertIn('block disappeared', self.sense('no markers remain'))
        self.assertIsNone(self.sense(self.good))
        self.seen.write_bytes(b'\xff')
        self.copy.write_bytes(b'\xff')
        report = self.sense(OPEN)
        self.assertIn('missing their pair', report)
        self.assertEqual(OPEN, self.seen.read_text(encoding='utf-8'))

    def test_incident_replay_reports_once_with_exact_pre_damage_copy(self):
        self.assertIsNone(self.sense())
        damaged = self.good.replace('', '### Next action\n\n等用户决定 web3studio 怎么部署。\n\n')
        report = self.sense(damaged)
        self.assertIn('block disappeared', report)
        self.assertIn(self.copy.relative_to(self.root).as_posix(), report)
        self.assertIn('If the change was intended, carry on: later edits are compared with this version.', report)
        self.assertEqual(self.good, self.copy.read_text(encoding='utf-8'))
        self.assertIsNone(self.sense())

    def test_threads_report_exactly_once(self):
        self.assertIsNone(self.sense())
        self.path.write_text(record('中' * 3100 + '\n', history='## History\n- second\n'), encoding='utf-8')
        barrier = threading.Barrier(16)

        def run(_):
            barrier.wait(timeout=20)
            return self.sense()

        with ThreadPoolExecutor(max_workers=16) as pool:
            reports = [r for r in pool.map(run, range(16)) if r]
        self.assertEqual(1, len(reports), reports)
        self.assertIn('earlier history entry', reports[0])
        self.assertEqual(self.good, self.copy.read_text(encoding='utf-8'))

    def test_subprocesses_report_exactly_once(self):
        self.assertIsNone(self.sense())
        self.path.write_text(OPEN, encoding='utf-8')
        source = (
            'import sys; from pathlib import Path; '
            'sys.path.insert(0, sys.argv[1]); '
            'from task_state_runtime import sense_selected_record; '
            'print("ready", flush=True); '
            'sys.stdin.readline(); '
            'print(sense_selected_record(Path(sys.argv[2]), state_file="tasks/fix.md") or "", end="")'
        )
        processes = [subprocess.Popen([sys.executable, '-c', source, str(CLI_PATH.parent), str(self.root)],
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      text=True) for _ in range(12)]
        try:
            for process in processes:
                self.assertEqual('ready\n', process.stdout.readline())
            for process in processes:
                process.stdin.write('\n')
                process.stdin.flush()
            outputs = [process.communicate(timeout=30) for process in processes]
            for process, (_, error) in zip(processes, outputs):
                self.assertEqual(0, process.returncode, error)
                self.assertEqual('', error)
            self.assertEqual(1, sum(bool(output) for output, _ in outputs), outputs)
            self.assertEqual(self.good, self.copy.read_text(encoding='utf-8'))
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.communicate()


class MarkerAndRecoveryRepairTests(unittest.TestCase):
    def test_bom_indent_and_unicode_line_separators(self):
        text = '\ufeff' + OPEN + '\nexact\n' + CLOSE + '\n'
        self.assertEqual('ok', RUNTIME.parse_current_state(text).status)
        self.assertEqual('exact\n', RUNTIME.parse_current_state(text).content)
        for spaces in (0, 1, 2, 3):
            block = (' ' * spaces + OPEN + '\nvalue\n' + ' ' * spaces + CLOSE + '\n')
            self.assertEqual('ok', RUNTIME.parse_current_state(block).status)
        self.assertEqual('absent', RUNTIME.parse_current_state('    ' + OPEN + '\nx\n    ' + CLOSE).status)
        # A leading tab is an indented code block in CommonMark, like four spaces.
        self.assertEqual('absent', RUNTIME.parse_current_state('\t' + OPEN + '\nx\n\t' + CLOSE).status)
        self.assertEqual('malformed', RUNTIME.parse_current_state(OPEN + '\nx\n    ' + CLOSE).status)
        self.assertEqual('absent', RUNTIME.parse_current_state('prefix\u2028' + OPEN + '\nx\n' + CLOSE + '\u2028suffix').status)
        self.assertEqual('ok', RUNTIME.parse_current_state(record('one\u2028two\n')).status)

    def test_long_paths_preserve_valid_block_and_extreme_path_is_identified(self):
        content = '中' * 2999 + '\n'
        path = 'a/' * 2495 + 'x.md'
        context = RUNTIME.render_recovery_context(relative_path=path, text=record(content))
        self.assertTrue(context.endswith(content))
        self.assertEqual(1, context.count(path))
        self.assertLessEqual(len(context), 9000)
        extreme = 'b/' * 5000 + 'extreme.md'
        context = RUNTIME.render_recovery_context(relative_path=extreme, text=record())
        self.assertIn(extreme[:197], context)
        self.assertIn('read the full record', context.casefold())
        self.assertLessEqual(len(context), 9000)

    def test_recovery_seeds_copy_before_first_tool_for_each_host(self):
        helper = host_tests.PostToolSensorTests(methodName='runTest')
        for host in ('codex', 'claude', 'zcode', 'kimi', 'grok'):
            with self.subTest(host=host), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                path = root / 'tasks/fix.md'
                path.parent.mkdir()
                path.write_text(record(), encoding='utf-8')
                event = 'UserPromptSubmit' if host == 'kimi' else 'SessionStart'
                first = helper.run_hook(host, root, event)
                self.assertNotIn('Task-state sensor', first)
                if host == 'grok':
                    self.assertEqual('', first)
                else:
                    self.assertTrue(first)
                copy = root / RUNTIME.snapshot_relative_path('tasks/fix.md')
                self.assertEqual(record(), copy.read_text(encoding='utf-8'))
                path.write_text(OPEN, encoding='utf-8')
                report = helper.run_hook(host, root, 'UserPromptSubmit' if host == 'kimi' else 'PostToolUse')
                self.assertIn('missing their pair', report)
                self.assertIn(copy.relative_to(root).as_posix(), report)
                self.assertEqual(record(), copy.read_text(encoding='utf-8'))
                if host == 'kimi':
                    self.assertLess(report.index('Task-state sensor'), report.index('Task-state recovery'))

    def test_grok_one_time_delivery_and_postcompact_also_seed(self):
        helper = host_tests.PostToolSensorTests(methodName='runTest')
        for event in ('PostToolUse', 'PostCompact'):
            with self.subTest(event=event), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                path = root / 'tasks/fix.md'
                path.parent.mkdir()
                path.write_text(record(), encoding='utf-8')
                output = helper.run_hook('grok', root, event)
                self.assertEqual(bool(output), event == 'PostToolUse')
                self.assertEqual(record(), (root / RUNTIME.snapshot_relative_path('tasks/fix.md')).read_text(encoding='utf-8'))


class CommandRepairTests(unittest.TestCase):
    def cli(self, root, *args, cwd=None):
        env = {k: v for k, v in os.environ.items() if not k.startswith('TASK_STATE_')}
        return subprocess.run([sys.executable, str(CLI_PATH), *args], cwd=cwd or root,
                              env=env, capture_output=True, text=True)

    def test_non_git_init_and_subdirectory_read_with_task_or_file(self):
        for selector, value in (('--task', 'demo'), ('--file', 'notes/design.md')):
            with self.subTest(selector=selector), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                initialized = self.cli(root, 'init', selector, value, '--objective', 'Real outcome')
                self.assertEqual(0, initialized.returncode, initialized.stderr)
                self.assertEqual('*\n', (root / '.task-state/.gitignore').read_text(encoding='utf-8'))
                child = root / 'src'
                child.mkdir()
                result = self.cli(root, 'read', selector, value, cwd=child)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual((root / initialized.stdout.strip()).read_text(encoding='utf-8'), result.stdout)
                self.assertTrue(result.stdout.startswith('# ' + ('demo' if selector == '--task' else 'design') + '\n'))

    def test_readme_ids_are_reserved_and_template_guidance_precedes_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for task in ('readme', 'README', 'ReadMe'):
                result = self.cli(root, 'init', '--task', task, '--objective', 'Reserved')
                self.assertEqual(2, result.returncode)
                self.assertFalse((root / 'tasks').exists())
            result = self.cli(root, 'init', '--task', 'real', '--objective', 'Objective')
            self.assertEqual(0, result.returncode, result.stderr)
            text = (root / result.stdout.strip()).read_text(encoding='utf-8')
            guidance = '<!-- Keep the current-state block true and short. Append to History; do not rewrite earlier entries. -->'
            self.assertLess(text.index(guidance), text.index(OPEN))
            self.assertEqual('', RUNTIME.parse_current_state(text).history.strip().removeprefix('## History').strip())

    @unittest.skipIf(os.name == 'nt', 'Creating symlinks requires Windows privileges')
    def test_escaping_legacy_binding_does_not_abort_activate_or_deactivate(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / 'project'
            root.mkdir()
            outside = base / 'outside'
            outside.mkdir()
            (root / '.tasks').symlink_to(outside, target_is_directory=True)
            (root / 'record.md').write_text(record(), encoding='utf-8')
            external = outside / '.sessions' / Path(RUNTIME.legacy_session_relative_path('owner')).name
            external.parent.mkdir()
            external.write_text('other.md\n', encoding='utf-8')
            selected = self.cli(root, 'activate', '--file', 'record.md', '--session', 'owner')
            self.assertEqual(0, selected.returncode, selected.stderr)
            binding = root / RUNTIME.session_relative_path('owner')
            self.assertTrue(binding.is_file())
            removed = self.cli(root, 'deactivate', '--session', 'owner')
            self.assertEqual(0, removed.returncode, removed.stderr)
            self.assertFalse(binding.exists())
            self.assertEqual('other.md\n', external.read_text(encoding='utf-8'))

    def test_check_failure_names_all_passing_copies_and_stays_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / 'record.md'
            for i in range(3):
                path.write_text(record(f'Next: {i}\n'), encoding='utf-8')
                result = self.cli(root, 'check', '--file', 'record.md')
                self.assertEqual(0, result.returncode, result.stderr)
            path.write_text(OPEN, encoding='utf-8')
            copy = Path(RUNTIME.snapshot_relative_path('record.md'))
            for _ in range(2):
                result = self.cli(root, 'check', '--file', 'record.md')
                self.assertEqual(1, result.returncode, result.stderr)
                for p in (copy, copy.with_suffix('.1.md'), copy.with_suffix('.2.md')):
                    self.assertIn(p.as_posix(), result.stdout)
                self.assertIn('Nothing was blocked.', result.stdout)


class SecondReviewRepairTests(unittest.TestCase):
    """Regressions from the second review: recovery, persisting oversize, manual check."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.path = self.root / 'tasks/fix.md'
        self.path.parent.mkdir()
        self.good = record()
        self.path.write_text(self.good, encoding='utf-8')
        self.environment = patch.dict(os.environ, {'TASK_STATE_DISABLED': '0'})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def sense(self, text=None):
        if text is not None:
            self.path.write_text(text, encoding='utf-8')
        return RUNTIME.sense_selected_record(self.root, state_file='tasks/fix.md')

    def recover(self):
        return RUNTIME.recovery_context_from_root(self.root, state_file='tasks/fix.md')

    def check(self):
        return subprocess.run([sys.executable, str(CLI_PATH), 'check', '--file', 'tasks/fix.md',
                               '--root', str(self.root)], capture_output=True, text=True)

    def test_recovery_never_consumes_damage_made_outside_hooked_tools(self):
        self.assertIsNone(self.sense())
        # A human edit, checkout or failed tool changes the record between sessions.
        self.path.write_text(self.good.replace('- first\n', ''), encoding='utf-8')
        self.assertIn('Next: verify.', self.recover())
        self.assertIn('earlier history entry', self.sense())
        self.assertIsNone(self.sense())
        self.assertEqual(1, self.check().returncode)

        self.assertIsNone(self.sense(self.good.replace('- first\n', '') + '- third\n'))
        markerless = self.path.read_text(encoding='utf-8').replace(OPEN + '\n', '').replace(CLOSE + '\n', '')
        self.path.write_text(markerless, encoding='utf-8')
        self.recover()
        self.assertIn('current-state block disappeared', self.sense())

    def test_oversize_block_that_keeps_changing_length_is_reported_once(self):
        self.assertIsNone(self.sense())
        self.assertIn('3001 characters', self.sense(record('中' * 3000 + '\n')))
        for extra in range(1, 7):
            self.assertIsNone(self.sense(record('中' * (3000 + extra * 10) + '\n')))
        self.assertIsNone(self.sense(self.good))
        self.assertIn('3001 characters', self.sense(record('中' * 3000 + '\n')))

    def test_manual_check_is_repeatable_and_independent_of_hook_baseline(self):
        self.assertIsNone(self.sense())
        damaged = self.good.replace('- first\n', '')
        self.assertIn('earlier history entry', self.sense(damaged))
        for _ in range(2):
            result = self.check()
            self.assertEqual(1, result.returncode, result.stdout)
            self.assertIn('earlier history entry', result.stdout)
            self.assertIn('this check changed nothing', result.stdout)
        self.path.write_text(self.good, encoding='utf-8')
        result = self.check()
        self.assertEqual(0, result.returncode, result.stdout)
        self.assertIn('OK: tasks/fix.md', result.stdout)

    def test_only_real_headings_are_ignored_in_history(self):
        numbered = record(history='## History\n- first\n#123 merged\n')
        self.assertIsNone(self.sense(numbered))
        self.assertIn("'#123 merged'", self.sense(numbered.replace('#123 merged\n', '')))

    def test_reserved_readme_id_still_reaches_a_legacy_record(self):
        legacy = self.root / '.tasks/readme.md'
        legacy.parent.mkdir()
        legacy.write_text(record(), encoding='utf-8')
        found = RUNTIME.resolve_state(self.root, task='readme', discover=False)
        self.assertEqual(('found', '.tasks/readme.md'), (found.status, found.relative_path))
        with tempfile.TemporaryDirectory() as other:
            self.assertEqual('invalid', RUNTIME.resolve_state(Path(other), task='readme', discover=False).status)


if __name__ == '__main__':
    unittest.main()
