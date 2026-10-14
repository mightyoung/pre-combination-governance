import importlib.util
from pathlib import Path
import sys
import unittest


PACKAGE = Path(__file__).resolve().parents[1]


def load_contract():
    module_path = PACKAGE / "result_contract.py"
    if not module_path.is_file():
        raise AssertionError("missing feature: complete frozen result contract")
    if str(PACKAGE) not in sys.path:
        sys.path.insert(0, str(PACKAGE))
    spec = importlib.util.spec_from_file_location("pcg_pair_result_contract", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def valid_result():
    return {
        "cards": {"a": "task:T:epoch:0"}, "possible": [],
        "risk": "EXPOSURE", "priority": "REVIEW", "notify": True,
        "fused": {"A@2": {"RUN": "4/5", "STOP": "0", "U": "1/5", "conflict": "0"}},
        "independent_evidence": 1,
        "role": "event rules shared; DS motion fusion diagnostic only",
        "context_evidence": {"status": "ABSENT", "accepted": [], "rejected": []},
        "notification_reasons": ["new_event_first_alert"], "card_updates": [],
        "risk_state_update": None, "review_notification_reasons": [],
    }


class FrozenResultContractTests(unittest.TestCase):
    def test_complete_valid_method_result_is_accepted(self):
        contract = load_contract()
        contract.validate_result(valid_result(), {"a"})

    def test_future_truth_fields_and_unknown_reasons_are_rejected(self):
        contract = load_contract()
        bad_truth = valid_result()
        bad_truth["oracle_episode"] = "hidden"
        with self.assertRaises(contract.ResultContractError):
            contract.validate_result(bad_truth, {"a"})
        bad_label = valid_result()
        bad_label["case_label"] = "I2_NO_INFO_NEW"
        with self.assertRaises(contract.ResultContractError):
            contract.validate_result(bad_label, {"a"})
        bad_reason = valid_result()
        bad_reason["notification_reasons"] = ["the_scorer_says_new_event"]
        with self.assertRaises(contract.ResultContractError):
            contract.validate_result(bad_reason, {"a"})

    def test_card_updates_must_reference_visible_alarm_ids(self):
        contract = load_contract()
        bad = valid_result()
        bad["card_updates"] = [{
            "id": "future-row", "kind": "possible_existing_event_update",
            "association_established": False, "review_required": True,
        }]
        with self.assertRaisesRegex(contract.ResultContractError, "card update"):
            contract.validate_result(bad, {"a"})

    def test_malformed_unhashable_values_fail_as_contract_errors(self):
        contract = load_contract()
        bad_possible = valid_result()
        bad_possible["possible"] = [{}]
        with self.assertRaises(contract.ResultContractError):
            contract.validate_result(bad_possible, {"a"})
        bad_risk = valid_result()
        bad_risk["risk"] = {"label": "EXPOSURE"}
        with self.assertRaises(contract.ResultContractError):
            contract.validate_result(bad_risk, {"a"})


if __name__ == "__main__":
    unittest.main()
