"""Release metadata and lockfile updates are validated before replacement."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import update_lvce


class UpdateLvce(unittest.TestCase):
    def release(self, tag='v0.116.0', **values):
        asset_name = f'lvce-{tag}_amd64.deb'
        return {
            'tag_name': tag,
            'draft': False,
            'prerelease': False,
            'assets': [{
                'name': asset_name,
                'browser_download_url': f'https://github.com/lvce-editor/lvce-editor/releases/download/{tag}/{asset_name}',
            }],
            **values,
        }

    def lockfile(self, root):
        path = root / 'editors.lock.json'
        path.write_text(json.dumps([
            {'id': 'lvce', 'name': 'LVCE Editor', 'version': 'v0.114.2', 'archive': 'old.deb',
             'url': 'https://example.invalid/old.deb', 'sha256': 'old',
             'binary': 'usr/lib/lvce/lvce', 'runtime': {'version': 'Electron 44.3.0'},
             'notes': 'keep this'},
            {'id': 'other', 'name': 'Other', 'version': '1', 'archive': 'other.tar.gz',
             'url': 'https://example.invalid/other.tar.gz', 'sha256': 'other'},
        ], indent=2) + '\n')
        return path

    @patch.object(update_lvce, 'fetch_json')
    def test_latest_metadata_rejects_prerelease(self, fetch):
        fetch.return_value = self.release(prerelease=True)
        with self.assertRaisesRegex(update_lvce.UpdateError, 'stable published'):
            update_lvce.release_metadata()

    @patch.object(update_lvce, 'fetch_json', return_value=[])
    def test_metadata_must_be_an_object(self, _fetch):
        with self.assertRaisesRegex(update_lvce.UpdateError, 'not an object'):
            update_lvce.release_metadata()

    @patch.object(update_lvce, 'fetch_json')
    def test_asset_must_match_release_tag(self, fetch):
        fetch.return_value = self.release(assets=[])
        with self.assertRaisesRegex(update_lvce.UpdateError, 'must contain exactly one'):
            update_lvce.find_asset(update_lvce.release_metadata())

    def test_update_preserves_other_entries_and_runtime(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self.lockfile(root)
            release = self.release()
            archive = b'validated deb bytes'
            with patch.object(update_lvce, 'release_metadata', return_value=release), \
                    patch.object(update_lvce, 'download', side_effect=lambda _url, target: target.write_bytes(archive)), \
                    patch.object(update_lvce, 'validate_archive'), \
                    patch.object(update_lvce, 'checksum', return_value=hashlib.sha256(archive).hexdigest()):
                self.assertTrue(update_lvce.update(lockfile=path))
                self.assertFalse(update_lvce.update(lockfile=path))
            editors = json.loads(path.read_text())
            lvce = next(editor for editor in editors if editor['id'] == 'lvce')
            self.assertEqual(lvce['version'], 'v0.116.0')
            self.assertEqual(lvce['archive'], 'lvce-v0.116.0_amd64.deb')
            self.assertEqual(lvce['runtime'], {'version': 'Electron 44.3.0'})
            self.assertEqual(lvce['notes'], 'keep this')
            self.assertEqual(editors[1]['id'], 'other')

    def test_download_failure_leaves_lockfile_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self.lockfile(root)
            original = path.read_bytes()
            release = self.release()
            with patch.object(update_lvce, 'release_metadata', return_value=release), \
                    patch.object(update_lvce, 'download', side_effect=update_lvce.UpdateError('download failed')):
                with self.assertRaisesRegex(update_lvce.UpdateError, 'download failed'):
                    update_lvce.update(lockfile=path)
            self.assertEqual(path.read_bytes(), original)

    @patch.object(update_lvce.subprocess, 'run')
    def test_archive_must_contain_lvce_binary(self, run):
        run.return_value.stdout = 'drwxr-xr-x root/root 0 2026-01-01 ./usr/lib/lvce/\n'
        with tempfile.NamedTemporaryFile() as archive:
            with self.assertRaisesRegex(update_lvce.UpdateError, 'does not contain'):
                update_lvce.validate_archive(Path(archive.name))


if __name__ == '__main__':
    unittest.main()
