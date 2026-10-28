"""Small data-independent checks of the consequential analysis rules (stdlib only)."""

from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analysis_core import (apply_corrections, check_expected, counts, decided_winner,
                           original_qualification)
from outputs import rounded


class AnalysisRules(unittest.TestCase):
    def test_both_either_is_observation_level(self):
        # Each scorer finds one F, but they find different observations.
        rows = [{'concern': 'C1', 'code_sonnet': 'F', 'code_qwen': 'P'},
                {'concern': 'C1', 'code_sonnet': 'P', 'code_qwen': 'F'}]
        self.assertEqual(counts(rows, 'F'), {'n': 2, 'lower': 0, 'higher': 2})
        self.assertEqual(counts(rows, 'FP'), {'n': 2, 'lower': 2, 'higher': 2})

    def test_single_qualified_scorer_replaces_both_endpoints(self):
        rows = [{'concern': 'C3', 'code_sonnet': 'F', 'code_qwen': 'P'},
                {'concern': 'C3', 'code_sonnet': 'P', 'code_qwen': 'F'}]
        self.assertEqual(counts(rows, 'F', {'C3': 'qwen'}),
                         {'n': 2, 'lower': 1, 'higher': 1})

    def test_correction_is_separate_and_old_code_is_checked(self):
        original = [{'blind_id': 'example', 'concern': 'C1', 'purpose': 'main',
                     'model': 'example-model', 'version': 'planted', 'prompt': 'Bare',
                     'code_sonnet': 'P', 'code_qwen': 'F',
                     'code_lower': 'P', 'code_higher': 'F'}]
        preserved = deepcopy(original)
        change = {'blind_id': 'example', 'concern': 'C1', 'coder': 'sonnet',
                  'old_code': 'P', 'recommended_code': 'F'}
        corrected, applied = apply_corrections(original, [change])
        self.assertEqual(original, preserved)
        self.assertEqual(corrected[0]['code_lower'], 'F')
        self.assertEqual(len(applied), 1)
        with self.assertRaises(ValueError):
            apply_corrections(original, [dict(change, old_code='–')])
        with self.assertRaises(ValueError):
            apply_corrections(original, [change, change])

    def test_original_failures_do_not_qualify_retroactively(self):
        original = [{'concern': 'C3', 'sonnet_passes': False, 'qwen_passes': True},
                    {'concern': 'C7', 'sonnet_passes': False, 'qwen_passes': False}]
        original_restriction = original_qualification(original)
        corrected = deepcopy(original)
        corrected[1]['qwen_passes'] = True
        self.assertNotEqual(original_restriction, original_qualification(corrected))
        self.assertEqual(original_restriction, {'included': ['C3'], 'excluded': ['C7'],
                                                'single_scorers': {'C3': 'qwen'}})

    def test_judgment_requires_same_review_across_orders(self):
        pair = {'review_1': 'one', 'review_2': 'two',
                'winner_review_1_shown_first': 'one',
                'winner_review_2_shown_first': 'one'}
        self.assertEqual(decided_winner(pair), 'one')
        pair['winner_review_2_shown_first'] = 'two'
        self.assertIsNone(decided_winner(pair))

    def test_expected_assertions_cannot_supply_calculations(self):
        result = {'computed': {'count': 3}}
        saved = deepcopy(result)
        checks = check_expected(result, {'assertions': [{'path': 'computed.count', 'value': 8}]})
        self.assertFalse(checks[0]['pass'])
        self.assertEqual(result, saved)

    def test_rounding_preserves_recorded_display_convention(self):
        self.assertEqual(rounded(1.25), '1.3')
        self.assertEqual(rounded(23.45), '23.5')


if __name__ == '__main__':
    unittest.main()
