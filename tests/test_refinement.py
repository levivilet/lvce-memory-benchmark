import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))
from refinement import next_budget, validate_trials
from metrics import summarize


def batch(budget, threshold=400, repeats=3):
    return [dict(editor='lvce', budgetMiB=budget, repeat=r,
                 status='passed' if budget is None or budget >= threshold else 'failed',
                 samples=[], final=dict(peak=0), probeMs=[])
            for r in range(1, repeats + 1)]


class RefinementTests(unittest.TestCase):
    def test_finds_400_between_384_and_512_and_replays(self):
        rows = batch(None) + batch(384) + batch(512)
        tested = []
        for _ in range(10):
            budget = next_budget(rows, 3)
            if budget is None:
                break
            tested.append(budget)
            rows.extend(batch(budget))
        self.assertEqual(tested, [448, 416, 400, 392, 396, 398, 399])
        validate_trials(rows, 'lvce', dict(repeats=3, budgets=[384, 512], refinement_iterations=10))
        summary = summarize(rows, 3, [384, 512])[0]
        self.assertEqual(summary['lowestTestedBudgetMiB'], 400)
        self.assertFalse(summary['atLowerBoundary'])
        self.assertEqual(len(summary['groups']), 10)

    def test_searches_below_grid_and_stops_at_one(self):
        rows = batch(64, 1)
        for _ in range(10):
            budget = next_budget(rows, 3)
            if budget is None:
                break
            rows.extend(batch(budget, 1))
        self.assertEqual(min(t['budgetMiB'] for t in rows), 1)
        self.assertTrue(summarize(rows, 3, [64])[0]['atLowerBoundary'])

    def test_no_passing_cap_or_empty_sweep(self):
        self.assertIsNone(next_budget(batch(None), 3))
        self.assertIsNone(next_budget(batch(128), 3))

    def test_partial_pass_does_not_qualify_and_nonmonotonic_sweep_is_kept(self):
        rows = batch(384) + batch(512) + batch(768, 900)
        partial = batch(448)
        partial[0]['status'] = 'failed'
        rows.extend(partial)
        self.assertEqual(next_budget(rows, 3), 480)
        self.assertEqual(next_budget(batch(512)[:2], 3), None)

    def test_rejects_truncated_duplicate_or_unexpected_refinement(self):
        initial = batch(None) + batch(384) + batch(512)
        protocol = dict(repeats=3, budgets=[384, 512], refinement_iterations=1)
        validate_trials(initial + batch(448), 'lvce', protocol)
        for extra in [[], batch(448)[:2], batch(440), batch(448) + batch(416), [batch(448)[0]] * 3]:
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                validate_trials(initial + extra, 'lvce', protocol)

    def test_iteration_limit_and_disabled_search(self):
        initial = batch(None) + batch(512)
        validate_trials(initial, 'lvce', dict(repeats=3, budgets=[512], refinement_iterations=0))
        validate_trials(initial + batch(256), 'lvce', dict(repeats=3, budgets=[512], refinement_iterations=1))

    def test_editor_specific_budgets_align_without_false_boundary(self):
        rows = batch(384) + batch(400) + batch(512)
        rows += [dict(t, editor='atom') for t in batch(384) + batch(448) + batch(512)]
        summaries = summarize(rows, 3, [384, 512])
        self.assertEqual([g['budgetMiB'] for g in summaries[0]['groups']],
                         [g['budgetMiB'] for g in summaries[1]['groups']])
        self.assertEqual(summaries[1]['groups'][2]['attempted'], 0)
        self.assertEqual(summaries[1]['lowestTestedBudgetMiB'], 448)
