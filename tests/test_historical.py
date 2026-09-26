import json
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import historical


class HistoricalTests(unittest.TestCase):
    @patch.object(historical, 'fetch_json')
    def test_inventory_filters_stable_releases_and_uses_requested_counts(self, fetch):
        lvce = [
            {'tag_name': 'v0.5.0', 'published_at': '2025-01-01', 'draft': False, 'prerelease': False},
            {'tag_name': 'v0.6.0-rc.1', 'published_at': '2025-03-01', 'draft': False, 'prerelease': True},
            {'tag_name': 'v0.7.0', 'published_at': '2025-02-01', 'draft': False, 'prerelease': False},
        ]
        vscode = ['1.10.0', '1.9.5', 'insider', '1.9.5']
        fetch.side_effect = [lvce, vscode]
        rows = historical.release_inventory(2)
        self.assertEqual(rows, [dict(editor='lvce', version='v0.7.0', archiveUrl='https://github.com/lvce-editor/lvce-editor/releases/download/v0.7.0/lvce-v0.7.0_amd64.deb'),
                                dict(editor='lvce', version='v0.5.0', archiveUrl='https://github.com/lvce-editor/lvce-editor/releases/download/v0.5.0/lvce-v0.5.0_amd64.deb'),
                                dict(editor='vscode', version='1.10.0', archiveUrl='https://update.code.visualstudio.com/1.10.0/linux-x64/stable'),
                                dict(editor='vscode', version='1.9.5', archiveUrl='https://update.code.visualstudio.com/1.9.5/linux-x64/stable')])

    def test_combine_omits_failed_versions_and_keeps_provenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / 'historical-lvce-v0.2.0'
            artifact.mkdir()
            (artifact / 'status.json').write_text(json.dumps(dict(editor='lvce', version='v0.2.0',
                status='succeeded', archiveUrl='https://official.example/app.deb', sha256='abc',
                runtime='Electron 4', runtimePolicy='bundled')))
            (artifact / 'results.json').write_text(json.dumps(dict(
                editors=[{'runtime': 'Electron 4'}],
                summaries=[{'editor': 'lvce', 'groups': [{'budgetMiB': None, 'qualified': True,
                    'metrics': {'pss': {'median': 10485760, 'min': 9437184, 'max': 11534336}}}]}])))
            failed = root / 'historical-vscode-1.0.0'
            failed.mkdir()
            (failed / 'status.json').write_text(json.dumps(dict(editor='vscode', version='1.0.0', status='failed')))
            inventory = root / 'inventory.json'
            inventory.write_text(json.dumps({'include': [dict(editor='vscode', version='1.1.0')]}))
            output = root / 'history.json'
            data = historical.combine(root, output, inventory)
            self.assertEqual((data['attempted'], data['succeeded'], data['failed']), (3, 1, 2))
            self.assertEqual(data['versions']['lvce'][0]['medianPssBytes'], 10485760)
            self.assertEqual(data['versions']['lvce'][0]['runtime'], 'Electron 4')
            self.assertEqual(data['versions']['lvce'][0]['runtimePolicy'], 'bundled')
            self.assertEqual(data['versions']['lvce'][0]['sha256'], 'abc')
            self.assertEqual(data['versions']['vscode'], [])
            self.assertEqual([row['version'] for row in data['failures']], ['1.0.0', '1.1.0'])
            self.assertEqual(json.loads(output.read_text()), data)

    def test_empty_history_is_a_valid_empty_dataset(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = historical.combine(root / 'missing', root / 'history.json')
            self.assertEqual((data['attempted'], data['succeeded'], data['failed']), (0, 0, 0))
            self.assertEqual(data['versions'], {'lvce': [], 'vscode': []})

    @patch.object(historical.update_lvce, 'validate_archive')
    @patch.object(historical, 'download')
    def test_prepare_pins_the_expected_release_url_and_records_archive_checksum(self, download, validate):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive_bytes = b'official package bytes'
            download.side_effect = lambda _url, path: path.write_bytes(archive_bytes)
            with patch.object(historical, 'ROOT', root):
                url = 'https://github.com/lvce-editor/lvce-editor/releases/download/v0.5.0/lvce-v0.5.0_amd64.deb'
                lockfile = historical.resolve('lvce', 'v0.5.0', root / 'attempt', url)
                entry = json.loads(lockfile.read_text())[0]
                self.assertEqual(entry['url'], url)
                self.assertEqual(entry['sha256'], hashlib.sha256(archive_bytes).hexdigest())
                self.assertIn('bundled', entry['runtimePolicy'])
                validate.assert_called_once()
                with self.assertRaisesRegex(ValueError, 'does not match'):
                    historical.resolve('lvce', 'v0.5.0', root / 'invalid', 'https://example.invalid/editor.deb')

    @patch.object(historical, 'release_inventory', return_value=[
        dict(editor='lvce', version='v0.5.0', archiveUrl='https://official.example/release.deb')])
    def test_inventory_creates_parent_directories_for_github_output_artifact(self, inventory):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / '.tmp/deep/inventory.json'
            with patch.object(sys, 'argv', ['historical.py', 'inventory', '--limit', '1', '--output', str(output)]):
                historical.main()
            self.assertEqual(json.loads(output.read_text()), {'include': inventory.return_value})

    @patch.object(historical.subprocess, 'run')
    def test_finalize_reads_exact_version_lockfile_when_results_json_is_also_present(self, run):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'attempt'
            historical.initialize('lvce', 'v0.5.0', root)
            entry = dict(id='lvce', binary='usr/lib/lvce/lvce', runtimePolicy='bundled runtime')
            (root / 'lvce-v0.5.0.json').write_text(json.dumps([entry]))
            (root / 'results.json').write_text(json.dumps({
                'editors': [{'url': 'https://official.example/lvce.deb', 'sha256': 'abc'}],
                'trials': [dict(budgetMiB=None, status='passed') for _ in range(3)],
            }))
            run.return_value.stdout = '44.3.0\n'
            with patch.object(historical, 'ROOT', Path(temporary)):
                historical.finalize('lvce', 'v0.5.0', root, 0, 'success', 'success', 'success')
            status = json.loads((root / 'status.json').read_text())
            self.assertEqual(status['status'], 'succeeded')
            self.assertEqual(status['runtime'], 'Electron 44.3.0 (bundled; not overridden)')
            self.assertEqual(status['archiveUrl'], 'https://official.example/lvce.deb')


if __name__ == '__main__':
    unittest.main()
