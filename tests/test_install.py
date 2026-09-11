"""Restored archives avoid network requests without bypassing verification."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import install


class ArchiveCache(unittest.TestCase):
    def run_installer(self, cached):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / '.tmp/apps/editor.tar.gz'
            archive.parent.mkdir(parents=True)
            data = b'official release archive'
            (root / 'editors.lock.json').write_text(json.dumps([{
                'id': 'lvce', 'version': '1', 'archive': archive.name,
                'url': 'https://example.invalid/editor.tar.gz',
                'sha256': hashlib.sha256(data).hexdigest(),
            }]))
            if cached is not None:
                archive.write_bytes(cached)

            def command(args, **kwargs):
                if args[0] == 'curl':
                    Path(args[args.index('--output') + 1]).write_bytes(data)

            with patch.object(install, 'ROOT', root), patch.object(sys, 'argv', ['install.py', '--editors', 'lvce']), patch.object(install.subprocess, 'run', side_effect=command) as run:
                if cached == b'corrupt':
                    with self.assertRaisesRegex(ValueError, 'Checksum mismatch'):
                        install.install()
                else:
                    install.install()
                return [call.args[0][0] for call in run.call_args_list]

    def test_cached_archive_is_extracted_without_download(self):
        self.assertEqual(self.run_installer(b'official release archive'), ['tar'])

    def test_cache_miss_downloads_and_extracts(self):
        self.assertEqual(self.run_installer(None), ['curl', 'tar'])

    def test_corrupt_cache_is_rejected_before_extraction(self):
        self.assertEqual(self.run_installer(b'corrupt'), [])
