"""Tests for behavior explicitly fixed by the public V2 business spec."""

from __future__ import annotations

import unittest

from rfb.research.alert_governance_v2 import (
    notification_kind_for_trigger,
    severity_for_risk_flag,
)


class PublicV2MappingsTests(unittest.TestCase):
    def test_public_trigger_types_use_pending_verification_risk_alert(self):
        trigger_types = (
            "ACTIVE_RISK_RELEVANT_EVIDENCE_CONFLICT",
            "UNCONFIRMED_EVENT_ASSOCIATION_WITH_ACTIVE_RISK",
            "MISSING_OR_REJECTED_BOUNDARY_WITH_ACTIVE_RISK",
        )

        for trigger_type in trigger_types:
            with self.subTest(trigger_type=trigger_type):
                self.assertEqual(
                    notification_kind_for_trigger(trigger_type),
                    "PENDING_VERIFICATION_RISK_ALERT",
                )

    def test_public_single_flag_severity_mappings_are_preserved(self):
        expected = {
            "EXPOSURE": "WARNING",
            "CONFLICT_REVIEW": "WARNING",
            "UNRESOLVED_RISK_RELEVANT_CONFLICT": "WARNING_RISK_UNRESOLVED",
            "EXPOSURE_HIGH": "CRITICAL",
        }

        for risk_flag, severity in expected.items():
            with self.subTest(risk_flag=risk_flag):
                self.assertEqual(severity_for_risk_flag(risk_flag), severity)

    def test_unknown_or_aggregated_flags_fail_closed(self):
        for risk_flag in ("UNKNOWN_FLAG", ("EXPOSURE", "EXPOSURE_HIGH")):
            with self.subTest(risk_flag=risk_flag):
                with self.assertRaises(ValueError):
                    severity_for_risk_flag(risk_flag)

    def test_unknown_trigger_fails_closed(self):
        with self.assertRaises(ValueError):
            notification_kind_for_trigger("UNSPECIFIED_TRIGGER")


if __name__ == "__main__":
    unittest.main()
