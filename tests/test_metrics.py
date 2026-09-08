import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))
from metrics import counters, process_memory, summarize


class MetricsTests(unittest.TestCase):
    def test_shared_memory_is_apportioned_not_added_twice(self):
        text = 'Pss: 120 kB\nRss: 200 kB\nPrivate_Clean: 40 kB\nPrivate_Dirty: 20 kB\nSwapPss: 3 kB\n'
        value = process_memory(text)
        self.assertEqual(value, dict(pss=122880, rss=204800, uss=61440, swapPss=3072))

    def test_missing_accounting_is_not_zero(self):
        with self.assertRaises(ValueError):
            process_memory('Pss: 5 kB\n')

    def test_event_counters(self):
        self.assertEqual(counters('oom 2\noom_kill 1\nhigh 0\n'), {'oom': 2, 'oom_kill': 1, 'high': 0})

    def row(self, budget, repeat, passed=True, value=100):
        return dict(editor='lvce', budgetMiB=budget, repeat=repeat, status='passed' if passed else 'failed',
                    samples=[dict(phase='idle', **dict.fromkeys(['pss','uss','rss','current','anon','file','kernel','processCount'], value))],
                    final=dict(peak=200), probeMs=[100, 200])

    def test_minimum_requires_every_repeat(self):
        trials=[self.row(b, r, passed=b!=128 or r!=3) for b in [128,256,512] for r in [1,2,3]]
        summary=summarize(trials,3,[128,256,512])[0]
        self.assertEqual(summary['lowestTestedBudgetMiB'],256)
        self.assertFalse(summary['atLowerBoundary'])
        self.assertEqual(summary['groups'][1]['passed'],2)

    def test_smoke_run_never_claims_minimum(self):
        self.assertIsNone(summarize([self.row(128,1)],1,[128])[0]['lowestTestedBudgetMiB'])

    def test_missing_repeat_is_unqualified(self):
        self.assertIsNone(summarize([self.row(128,1),self.row(128,2)],3,[128])[0]['lowestTestedBudgetMiB'])

    def test_duplicate_repeat_is_unqualified(self):
        self.assertIsNone(summarize([self.row(128,1)]*3,3,[128])[0]['lowestTestedBudgetMiB'])

    def test_all_failed_is_not_zero_memory(self):
        summary=summarize([self.row(128,r,False) for r in [1,2,3]],3,[128])[0]
        self.assertIsNone(summary['lowestTestedBudgetMiB'])
        self.assertIsNone(summary['groups'][1]['metrics']['pss'])

    def test_boundary_and_equal_run_weight(self):
        rows=[self.row(128,r,value=v) for r,v in [(1,100),(2,300),(3,200)]]
        rows[0]['samples'] *= 10
        summary=summarize(rows,3,[128])[0]
        self.assertTrue(summary['atLowerBoundary'])
        self.assertEqual(summary['groups'][1]['metrics']['pss'],dict(min=100,median=200,max=300))

    def test_non_monotonic_outcomes_do_not_hide_lower_success(self):
        rows=[self.row(b,r,passed=b!=256) for b in [128,256,512] for r in [1,2,3]]
        self.assertEqual(summarize(rows,3,[128,256,512])[0]['lowestTestedBudgetMiB'],128)


if __name__ == '__main__':
    unittest.main()
