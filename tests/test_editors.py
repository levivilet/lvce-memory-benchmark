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
        self.assertTrue({'eclipse', 'idea', 'atom', 'lapce', 'theia'} <= {e['id'] for e in editors})
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
