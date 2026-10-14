"""Two regression bundles, prepared only; original T3 oracle is unchanged."""
import copy
import json
from pathlib import Path
import unittest
from worker import run, continuing_context_candidate


class NotificationTests(unittest.TestCase):
    def test_uncertain_card_update_is_not_repeated_physical_alert(self):
        public = json.loads((Path(__file__).parent / 'public-input.json').read_text())
        # Both cases computed inside this declared test bundle, not main slots.
        row = next(r for r in run(public)['rows'] if r['trace'] == 'N1_UNCERTAIN_UPDATE'
                   and r['prefix'] == 5 and r['method'] == 'M1')['result']
        self.assertEqual(row['risk'], 'EXPOSURE')
        self.assertEqual(row['possible'], ['e'])
        self.assertEqual(row['cards']['e'], 'uncertain:e')
        self.assertFalse(any(r != 'handling_follow_up_only' for r in row['notification_reasons']))
        self.assertEqual(row['card_updates'], [{'id': 'e', 'kind': 'possible_existing_event_update',
                                               'association_established': False, 'review_required': True}])
        # Negative boundary checks inside this test bundle; no extra main slots.
        rows = public['traces'][0]['rows']
        for field, value in [('asset', 'C'), ('task', 'OTHER'), ('target', 'temperature'), ('quality', 'BAD')]:
            new = copy.deepcopy(rows[-1])
            new[field] = value
            self.assertFalse(continuing_context_candidate(new, rows[:-1], 4))
        self.assertFalse(continuing_context_candidate(rows[-1], rows[:-1], 10))
        earlier = copy.deepcopy(rows[:-1])
        earlier[-1]['recovery'] = True
        self.assertFalse(continuing_context_candidate(rows[-1], earlier, 4))

    def test_current_high_evidence_escalates_without_forcing_association(self):
        public = json.loads((Path(__file__).parent / 'public-input.json').read_text())
        row = next(r for r in run(public)['rows'] if r['trace'] == 'N2_RISK_ESCALATION'
                   and r['prefix'] == 5 and r['method'] == 'M1')['result']
        self.assertEqual(row['risk'], 'EXPOSURE_HIGH')
        self.assertEqual(row['possible'], ['e'])
        self.assertEqual(row['cards']['e'], 'uncertain:e')
        self.assertIn('risk_escalation', row['notification_reasons'])
        self.assertNotIn('new_event_first_alert', row['notification_reasons'])
        self.assertEqual(row['risk_state_update'], {'from': 'EXPOSURE', 'to': 'EXPOSURE_HIGH'})
