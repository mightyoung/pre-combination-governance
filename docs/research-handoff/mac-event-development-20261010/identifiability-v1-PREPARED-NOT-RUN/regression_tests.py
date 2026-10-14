"""Six public gate-test bundles; no assess calls or physical-label imports."""
import copy
import json
from pathlib import Path
import unittest
from shared_context import resolve


def fixture(name):
    public = json.loads((Path(__file__).parent / 'public-input.json').read_text())
    return copy.deepcopy(next(t['rows'] for t in public['traces'] if t['id'] == name))


class ContextTests(unittest.TestCase):
    def test_explicit_recovery(self):
        self.assertEqual(resolve(fixture('I3_RECOVERY'))['status'], 'NEW_BOUNDARY')

    def test_closed_and_opened_work_round(self):
        self.assertEqual(resolve(fixture('I4_WORK_ROUND'))['status'], 'NEW_BOUNDARY')

    def test_independent_state_transition(self):
        self.assertEqual(resolve(fixture('I5_INDEPENDENT_STATE'))['status'], 'NEW_BOUNDARY')

    def test_future_and_stale_timing_rejected(self):
        for field, value in [('known_time', 5), ('physical_time', 1)]:
            rows = fixture('I3_RECOVERY')
            rows[-1]['boundary_evidence'][0][field] = value
            self.assertEqual(resolve(rows)['status'], 'UNKNOWN_REVIEW')

    def test_quality_qualification_and_lineage_rejected(self):
        for field, value in [('quality', 'BAD'), ('reliability', 'UNQUALIFIED'),
                             ('independent_lineage', False), ('acquisition', 'c')]:
            rows = fixture('I3_RECOVERY')
            rows[-1]['boundary_evidence'][0][field] = value
            self.assertEqual(resolve(rows)['status'], 'UNKNOWN_REVIEW')

    def test_conflicting_rounds_and_combined_invalid_case(self):
        rows = fixture('I4_WORK_ROUND')
        other = copy.deepcopy(rows[-1]['boundary_evidence'][0])
        other.update(value='W3', source_id='ledger-R', acquisition='round-R')
        rows[-1]['boundary_evidence'].append(other)
        self.assertEqual(resolve(rows)['status'], 'UNKNOWN_REVIEW')
        self.assertEqual(resolve(fixture('I6_INVALID_CONTEXT'))['status'], 'UNKNOWN_REVIEW')
        rows = fixture('I4_WORK_ROUND')
        rows[-1]['boundary_evidence'].append(copy.deepcopy(rows[-1]['boundary_evidence'][0]))
        self.assertEqual(resolve(rows)['status'], 'UNKNOWN_REVIEW')
