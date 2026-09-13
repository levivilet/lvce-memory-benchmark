import copy
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))
from combine import combine


class CombineTests(unittest.TestCase):
    def setUp(self):
        self.editors = ['lvce', 'vscode', 'zed', 'geany', 'eclipse', 'idea', 'atom', 'lapce', 'theia', 'basic-electron']
        self.results = [dict(
            schemaVersion=1, commit='commit', runUrl='run', fixtureSha256='fixture',
            capturedAt=f'2026-09-09T00:00:0{index}Z', host=dict(cpu=f'CPU {index}'),
            protocol=dict(editors=editor, repeats=3, budgets=[128], seed=1729),
            editors=[dict(id=editor, name=editor, version='1')],
            trials=[dict(editor=editor, budgetMiB=budget, repeat=repeat,
                         status='failed', samples=[], error='OOM', probeMs=[])
                    for budget in [None, 128] for repeat in range(1, 4)],
        ) for index, editor in enumerate(self.editors)]

    def test_preserves_hosts_versions_failed_trials_and_execution_order(self):
        self.results[0]['trials'].reverse()
        original = copy.deepcopy(self.results)
        data = combine(list(reversed(self.results)), self.editors)
        self.assertEqual(data['editors'], [r['editors'][0] for r in self.results])
        self.assertEqual(data['trials'], [t for r in self.results for t in r['trials']])
        self.assertEqual(data['hosts'], {e: r['host'] for e, r in zip(self.editors, self.results)})
        self.assertNotIn('host', data)
        self.assertEqual(data['capturedAt'], self.results[0]['capturedAt'])
        self.assertEqual(data['capturedAtByEditor']['zed'], self.results[2]['capturedAt'])
        self.assertEqual(data['protocol']['editors'], ','.join(self.editors))
        self.assertEqual(len(data['summaries']), len(self.editors))
        self.assertTrue(all(s['lowestTestedBudgetMiB'] is None for s in data['summaries']))
        self.assertEqual(self.results, original)

    def test_missing_empty_duplicate_and_unexpected_artifacts(self):
        for results in [[], self.results[:-1], self.results + [self.results[0]]]:
            with self.subTest(count=len(results)), self.assertRaises(ValueError):
                combine(results, self.editors)
        with self.assertRaises(ValueError):
            combine(self.results, ['lvce'])

    def test_rejects_mismatched_provenance_and_protocol(self):
        for key, value in [('schemaVersion', 2), ('commit', 'other'), ('runUrl', 'other'),
                           ('fixtureSha256', 'other'), ('protocol', dict(editors='lvce', repeats=1, budgets=[]))]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                results = copy.deepcopy(self.results)
                results[0][key] = value
                combine(results, self.editors)

    def test_rejects_missing_duplicate_and_foreign_trials(self):
        for replacement in [[], [self.results[0]['trials'][0]] * 6, self.results[1]['trials']]:
            with self.subTest(trials=replacement), self.assertRaises(ValueError):
                results = copy.deepcopy(self.results)
                results[0]['trials'] = replacement
                combine(results, self.editors)

    def test_rejects_pooling_editors_and_incorrect_selection(self):
        results = copy.deepcopy(self.results)
        results[0]['editors'] += results[1]['editors']
        with self.assertRaises(ValueError):
            combine(results, self.editors)
        self.results[0]['protocol']['editors'] = 'lvce,vscode'
        with self.assertRaises(ValueError):
            combine(self.results, self.editors)


if __name__ == '__main__':
    unittest.main()
