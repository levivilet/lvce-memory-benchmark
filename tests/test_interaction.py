"""Window replacement must be recovered before any edit is injected."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import benchmark


class InteractionTests(unittest.TestCase):
    def test_editors_without_file_titles_keep_owned_window_selection(self):
        search = subprocess.CompletedProcess([], 0, stdout='editor\n')
        with patch('benchmark.pids', return_value=[42]), \
                patch('benchmark.subprocess.run', return_value=search), \
                patch('benchmark.run', side_effect=['42', 'WIDTH=1280']):
            self.assertEqual(benchmark.window_for(Path('/group')), 'editor')

    def test_window_selection_ignores_splash_and_unrelated_processes(self):
        def run(args):
            window = args[-1]
            if args[1] == 'getwindowpid':
                return '99' if window == 'unrelated' else '42'
            if args[1] == 'getwindowname':
                return 'IntelliJ IDEA' if window == 'splash' else 'memory-benchmark.txt - Editor'
            return 'WIDTH=1280\nHEIGHT=720'

        search = subprocess.CompletedProcess([], 0, stdout='splash\nunrelated\neditor\n')
        with patch('benchmark.pids', return_value=[42]), \
                patch('benchmark.subprocess.run', return_value=search), \
                patch('benchmark.run', side_effect=run):
            self.assertEqual(benchmark.window_for(Path('/group'), 'memory-benchmark.txt'), 'editor')

    def test_probe_reacquires_a_replaced_window_before_typing(self):
        with tempfile.TemporaryDirectory() as temporary:
            file = Path(temporary) / 'memory-benchmark.txt'
            file.write_text('marker' + benchmark.FIXTURE)
            commands = []

            def run(args):
                commands.append(args)
                if args[1] in ('windowsize', 'windowactivate') and 'current' not in args:
                    raise subprocess.CalledProcessError(1, args, stderr='BadWindow')
                return ''

            with patch('benchmark.window_for', side_effect=['expired', 'current']) as windows, \
                    patch('benchmark.run', side_effect=run), patch('benchmark.time.sleep'):
                benchmark.probe(Path('/group'), file, 'marker', 5)
            self.assertEqual(windows.call_count, 2)
            self.assertEqual(sum(args[1] == 'type' for args in commands), 1)
            self.assertIn(['xdotool', 'windowactivate', '--sync', 'current'], commands)

    def test_missing_window_has_a_deadline_and_never_types(self):
        with patch('benchmark.window_for', return_value=None), \
                patch('benchmark.time.monotonic', side_effect=range(100)), \
                patch('benchmark.time.sleep'), patch('benchmark.run') as run:
            with self.assertRaises(TimeoutError):
                benchmark.probe(Path('/group'), Path('/unused'), 'marker', 5)
        run.assert_not_called()

    def test_window_accounting_errors_are_not_retried(self):
        with patch('benchmark.window_for', side_effect=PermissionError) as windows, \
                patch('benchmark.run') as run:
            with self.assertRaises(PermissionError):
                benchmark.probe(Path('/group'), Path('/unused'), 'marker', 5)
        windows.assert_called_once()
        run.assert_not_called()

    def test_failed_edit_is_not_retried(self):
        with tempfile.TemporaryDirectory() as temporary:
            file = Path(temporary) / 'memory-benchmark.txt'
            file.write_text(benchmark.FIXTURE)
            with patch('benchmark.window_for', return_value='current') as windows, \
                    patch('benchmark.run') as run, patch('benchmark.time.sleep'), \
                    patch('benchmark.time.monotonic', side_effect=range(100)):
                with self.assertRaises(TimeoutError):
                    benchmark.probe(Path('/group'), file, 'marker', 5)
            self.assertEqual(windows.call_count, 1)
            self.assertEqual(sum(call.args[0][1] == 'type' for call in run.call_args_list), 1)
