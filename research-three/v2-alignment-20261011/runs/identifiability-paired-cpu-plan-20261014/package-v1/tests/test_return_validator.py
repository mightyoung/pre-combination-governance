import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


PACKAGE = Path(__file__).resolve().parents[1]
CASE_IDS = [
    "38e02496822f1a85849b6a39f698e50d", "33fadeeedeed902bd0ab9dfae5420213",
    "42474559127419126b713096e9f4d3ee", "81050a121e028f59f1e6940d7c5eb477",
]
METHODS = ["M0", "M1", "M2", "M3"]


def load_module(name):
    if name in sys.modules:
        return sys.modules[name]
    module_path = PACKAGE / (name + ".py")
    if not module_path.is_file():
        raise AssertionError("missing feature: " + name + " is not implemented")
    if str(PACKAGE) not in sys.path:
        sys.path.insert(0, str(PACKAGE))
    spec = importlib.util.spec_from_file_location("pcg_pair_" + name, module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.modules[name] = module
    return module


class ReturnValidatorTests(unittest.TestCase):
    def test_partial_failure_is_valid_only_with_actual_counts_and_reason(self):
        bundle = load_module("bundle")
        validator = load_module("return_validator")
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp) / "run"
            run_dir.mkdir()
            slot = {
                "case_id": CASE_IDS[0], "prefix": 1, "method": "M0",
                "input_sha256": "a" * 64, "output_sha256": "b" * 64,
                "result": {
                    "cards": {"a": "card-a"}, "possible": [],
                    "notification_reasons": [], "risk": "EXPOSURE",
                    "priority": "REVIEW", "notify": False, "fused": {},
                    "independent_evidence": 0,
                    "role": "event rules shared; DS motion fusion diagnostic only",
                    "context_evidence": {"status": "ABSENT", "accepted": [], "rejected": []},
                    "card_updates": [], "risk_state_update": None,
                    "review_notification_reasons": [],
                },
            }
            attempt = {
                "run_id": "synthetic-partial", "attempt_count": 1,
                "task_id": "PCG-IDENTIFIABILITY-PAIRED-CPU-001",
                "task_status": "FAIL", "research_acceptance": "NOT_EVALUATED",
                "planned_method_invocations": 80, "method_start_requests": 2,
                "method_invocations_started": 2,
                "completed_method_invocations": 1, "partial": True,
                "stop_reason": "synthetic_child_exit", "terminal_exit_code": 30,
                "case_ids": CASE_IDS,
                "method_order": METHODS,
            }
            bundle.freeze_bundle(run_dir, [slot], attempt)
            report = validator.validate_return(run_dir)
            self.assertEqual("VALID_PARTIAL_EXECUTION", report["validation_status"])
            self.assertEqual(1, report["completed_method_invocations"])
            self.assertEqual("NOT_EVALUATED", report["research_acceptance"])

    def test_complete_pass_requires_matching_score_receipt(self):
        bundle = load_module("bundle")
        load_module("scorer")
        validator = load_module("return_validator")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run_dir = root / "run"
            run_dir.mkdir()
            manifest_path = PACKAGE / "TASK_MANIFEST.json"
            manifest = json.loads(manifest_path.read_text())
            pair_path = PACKAGE / manifest["pair_inputs_path"]
            pair_inputs = json.loads(pair_path.read_text())
            previous = {(case_id, method): {} for case_id in CASE_IDS for method in METHODS}
            slots = []
            for case in pair_inputs["cases"]:
                case_id = case["case_id"]
                for prefix in range(1, 6):
                    visible = case["rows"][:prefix]
                    cards = {row["id"]: "card-" + row["id"]
                             for row in visible if row.get("alarm") is True}
                    for method in METHODS:
                        result = {
                            "cards": cards, "possible": [], "risk": "EXPOSURE",
                            "priority": "REVIEW", "notify": False, "fused": {},
                            "independent_evidence": 0,
                            "role": "event rules shared; DS motion fusion diagnostic only",
                            "context_evidence": {"status": "ABSENT", "accepted": [], "rejected": []},
                            "notification_reasons": [], "card_updates": [],
                            "risk_state_update": None, "review_notification_reasons": [],
                        }
                        payload = {"method": method, "prefix": visible,
                                   "old": previous[(case_id, method)]}
                        slots.append({
                            "case_id": case_id, "prefix": prefix, "method": method,
                            "input_sha256": hashlib.sha256(bundle.canonical_bytes(payload)).hexdigest(),
                            "output_sha256": hashlib.sha256(bundle.canonical_bytes(result)).hexdigest(),
                            "result": result,
                        })
                        previous[(case_id, method)] = {
                            key: result[key] for key in ("cards", "risk", "priority")
                        }
            attempt = {
                "run_id": "synthetic-pass", "attempt_count": 1,
                "task_id": "PCG-IDENTIFIABILITY-PAIRED-CPU-001",
                "task_status": "PASS", "research_acceptance": "NOT_EVALUATED",
                "planned_method_invocations": 80, "method_start_requests": 80,
                "method_invocations_started": 80,
                "completed_method_invocations": 80, "partial": False,
                "stop_reason": None, "terminal_exit_code": 0,
                "case_ids": CASE_IDS, "method_order": METHODS,
                "task_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                "source_commits": manifest["source_commits"],
                "schema_hashes": manifest["schema_hashes"],
                "public_input_sha256": manifest["public_input_sha256"],
                "pair_inputs_sha256": manifest["pair_inputs_sha256"],
                "oracle_sha256": manifest["oracle_sha256"],
                "oracle_case_map_sha256": manifest["oracle_case_map_sha256"],
                "plan_sha256": manifest["plan_sha256"],
            }
            receipt = bundle.freeze_bundle(run_dir, slots, attempt)
            score_path = root / "score.json"
            scorer = load_module("scorer")
            scorer.score_bundle(
                run_dir, manifest_path,
                PACKAGE / "scorer_source" / "oracle.physical.json",
                PACKAGE / "scorer_source" / "ORACLE_CASE_MAP.json",
                score_path,
            )
            valid = validator.validate_return(
                run_dir, score_path, manifest_path,
                PACKAGE / "scorer_source" / "oracle.physical.json",
                PACKAGE / "scorer_source" / "ORACLE_CASE_MAP.json",
            )
            self.assertEqual("VALID_COMPLETE_RETURN", valid["validation_status"])
            forged = json.loads(score_path.read_text())
            forged["first_alert_checks"].pop()
            score_path.write_text(json.dumps(forged))
            with self.assertRaisesRegex(validator.ReturnValidationError, "differ from the deterministic scorer"):
                validator.validate_return(
                    run_dir, score_path, manifest_path,
                    PACKAGE / "scorer_source" / "oracle.physical.json",
                    PACKAGE / "scorer_source" / "ORACLE_CASE_MAP.json",
                )


if __name__ == "__main__":
    unittest.main()
