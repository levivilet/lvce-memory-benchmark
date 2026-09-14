"""Verify a runtime replacement preserves app bytes and rejects corrupt downloads."""
import importlib.util
import json
import hashlib
from pathlib import Path
import tempfile
import unittest
import zipfile

root = Path(__file__).resolve().parents[1]
script = root / ('scripts/install.py' if (root / 'editors.lock.json').exists() else 'vendor/benchmark/scripts/install.py')
spec = importlib.util.spec_from_file_location('installer', script)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)

class RuntimeOverride(unittest.TestCase):
    def fixture(self, temporary):
        target = Path(temporary)
        archive = target / 'runtime.zip'
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('electron', '#!/bin/sh\nprintf "44.3.0\\n"\n')
            z.writestr('resources/default_app.asar', b'new default app')
            z.writestr('new-library.so', b'new runtime')
        destination = target / 'lvce'
        runtime = destination / 'usr/lib/lvce'
        (runtime / 'resources/app').mkdir(parents=True)
        (runtime / 'resources/app/main.js').write_bytes(b'unchanged application')
        (runtime / 'old-library.so').write_bytes(b'stale')
        editor = {'binary': 'usr/lib/lvce/lvce', 'runtime': {'directory': 'usr/lib/lvce', 'archive': 'runtime.zip', 'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(), 'version': 'Electron 44.3.0'}}
        return target, destination, runtime, editor

    def test_runtime_is_replaced_and_application_bytes_are_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            target, destination, runtime, editor = self.fixture(temporary)
            installer.install_runtime(editor, target, destination)
            self.assertEqual((runtime / 'resources/app/main.js').read_bytes(), b'unchanged application')
            self.assertFalse((runtime / 'old-library.so').exists())
            self.assertTrue((runtime / 'new-library.so').exists())
            self.assertTrue((runtime / 'lvce').stat().st_mode & 0o111)

    def test_bad_checksum_does_not_touch_application_or_runtime(self):
        with tempfile.TemporaryDirectory() as temporary:
            target, destination, runtime, editor = self.fixture(temporary)
            editor['runtime']['sha256'] = '0' * 64
            with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                installer.install_runtime(editor, target, destination)
            self.assertEqual((runtime / 'resources/app/main.js').read_bytes(), b'unchanged application')
            self.assertTrue((runtime / 'old-library.so').exists())

if __name__ == '__main__':
    unittest.main()
