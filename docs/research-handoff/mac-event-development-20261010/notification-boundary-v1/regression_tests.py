"""Five diagnostic bundles; hand-labelled oracle not changed to pass methods."""
import json
from pathlib import Path
import unittest
from worker import step


def fixture(name):
    public = json.loads((Path(__file__).parent / 'public-input.json').read_text())
    return next(t['rows'] for t in public['traces'] if t['id'] == name)


def old(risk='EXPOSURE', card='task:J:epoch:0', priority='FOLLOW_UP'):
    return {'risk': risk, 'cards': {'a': card}, 'priority': priority}


class BoundaryTests(unittest.TestCase):
    def test_new_independent_event_first_alert(self):
        result = step(fixture('B1_NEW_INDEPENDENT')[:4], 'M1', old())
        self.assertEqual(result['risk'], 'EXPOSURE')
        self.assertIn('new_event_first_alert', result['notification_reasons'])
        self.assertNotIn('risk_escalation', result['notification_reasons'])
        self.assertNotEqual(result['cards']['a'], result['cards']['d'])

    def test_confirmed_recovery_then_recurrence(self):
        result = step(fixture('B2_RECOVERY_RECURRENCE')[:3], 'M1', old('UNKNOWN', priority='REVIEW'))
        self.assertNotEqual(result['cards']['a'], result['cards']['c'])
        self.assertEqual(result['risk'], 'EXPOSURE')
        self.assertIn('new_event_first_alert', result['notification_reasons'])

    def test_downgrade_state_then_new_high_upgrade(self):
        rows = fixture('B3_DOWN_THEN_UP')
        down = step(rows[:2], 'M1', old('EXPOSURE_HIGH', priority='REVIEW'))
        self.assertEqual(down['risk_state_update'], {'from': 'EXPOSURE_HIGH', 'to': 'EXPOSURE'})
        self.assertFalse(down['notification_reasons'])
        up = step(rows[:4], 'M1', old('EXPOSURE'))
        self.assertEqual(up['risk'], 'EXPOSURE_HIGH')
        self.assertIn('risk_escalation', up['notification_reasons'])

    def test_identical_continuing_event_keeps_review(self):
        result = step(fixture('B4_IDENTICAL_CONTINUING'), 'M1', old())
        self.assertEqual(result['possible'], ['e'])
        self.assertEqual(result['notification_reasons'], [])
        self.assertEqual(result['review_notification_reasons'], ['uncertain_new_alarm_requires_review'])
        self.assertFalse(result['card_updates'][0]['association_established'])

    def test_identical_hidden_event_is_not_claimed_physically_identified(self):
        self.assertEqual(fixture('B4_IDENTICAL_CONTINUING'), fixture('B5_IDENTICAL_NEW_HIDDEN'))
        result = step(fixture('B5_IDENTICAL_NEW_HIDDEN'), 'M1', old())
        self.assertEqual(result['possible'], ['e'])
        self.assertEqual(result['review_notification_reasons'], ['uncertain_new_alarm_requires_review'])
        # Diagnostic limitation: this deliberately does not assert safety.
        # Physical oracle still requires prefix5 first alert for hidden E2.
        self.assertEqual(result['notification_reasons'], [])
