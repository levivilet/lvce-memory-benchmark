"""Keep launch adapters explicit and profiles independent between trials."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from benchmark import profile_config


class EditorProfiles(unittest.TestCase):
    def test_every_locked_editor_has_an_isolated_launch_adapter(self):
        root = Path(__file__).resolve().parents[1]
        editors = json.loads((root / 'editors.lock.json').read_text())
        self.assertTrue({'eclipse', 'idea', 'atom', 'lapce', 'theia', 'basic-electron'} <= {e['id'] for e in editors})
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            installation = base / 'installation'
            (installation / 'configuration').mkdir(parents=True)
            (installation / 'configuration/config.ini').write_text('original configuration')
            for editor in [*editors, {'id': 'geany'}]:
                editor['command'] = str(installation / 'editor')
                first, second = base / editor['id'] / 'first', base / editor['id'] / 'second'
                for home in [first, second]:
                    args = profile_config(editor, home)
                    self.assertTrue(args, editor['id'])
                    self.assertNotIn(str(first if home == second else second), ' '.join(map(str, args)))
                if editor['id'] == 'eclipse':
                    (first / 'eclipse-configuration/config.ini').write_text('modified')
                    self.assertEqual((second / 'eclipse-configuration/config.ini').read_text(), 'original configuration')
                if editor['id'] == 'idea':
                    properties = (second / 'idea.properties').read_text()
                    self.assertNotIn(str(first), properties)
                    for directory in ['idea-config', 'idea-system', 'idea-plugins', 'idea-log']:
                        self.assertIn(str(second / directory), properties)
                    self.assertIn('-e', args)

    def test_unknown_editor_cannot_inherit_geany_arguments(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, 'Unsupported editor'):
                profile_config({'id': 'unknown'}, Path(temporary))

    def test_basic_electron_uses_the_checked_in_app_and_isolates_the_profile(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            args = profile_config({'id': 'basic-electron', 'app': 'basic-electron'}, Path(temporary))
        self.assertIn(str(root / 'basic-electron'), ' '.join(map(str, args)))
        self.assertIn('--no-sandbox', args)
        self.assertIn('--ozone-platform=x11', args)

    def test_basic_electron_keeps_file_io_in_the_main_process(self):
        root = Path(__file__).resolve().parents[1]
        main = (root / 'basic-electron/main.js').read_text()
        renderer = (root / 'basic-electron/renderer.js').read_text()
        html = (root / 'basic-electron/index.html').read_text()
        self.assertIn("ipcMain.handle('read-file'", main)
        self.assertIn("ipcMain.handle('write-file'", main)
        self.assertIn('id="save"', html)
        self.assertIn('id="editor"', html)
        self.assertIn('writeFile(editor.value)', renderer)
        self.assertIn("event.key.toLowerCase() === 's'", renderer)
