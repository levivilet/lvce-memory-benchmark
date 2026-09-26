from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from benchmark import protocol_options


class BenchmarkProtocolTests(unittest.TestCase):
    def test_protocol_excludes_local_paths_but_keeps_measurement_options(self):
        options = {
            'output': Path('results/custom.json'),
            'lockfile': Path('.tmp/historical/lvce.json'),
            'editors': 'lvce',
            'repeats': 3,
            'budgets': '128,256',
        }
        self.assertEqual(protocol_options(options), {
            'editors': 'lvce', 'repeats': 3, 'budgets': '128,256',
        })


if __name__ == '__main__':
    unittest.main()
