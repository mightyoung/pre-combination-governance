import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


PACKAGE = Path(__file__).resolve().parents[1]


def load_runner():
    if str(PACKAGE) not in sys.path:
        sys.path.insert(0, str(PACKAGE))
    spec = importlib.util.spec_from_file_location("pcg_pair_package_runner", PACKAGE / "runner.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PackageContractTests(unittest.TestCase):
    def test_manifest_applies_unambiguous_approvals_and_keeps_wall_scope_blocked(self):
        manifest = json.loads((PACKAGE / "TASK_MANIFEST.json").read_text())
        self.assertEqual("BLOCKED_MISSING_VALUES", manifest["resource_profile_status"])
        self.assertEqual({"cpu_quota_millis": 1000, "wall_seconds": None,
                          "memory_bytes": 268435456, "pids_limit": 16,
                          "max_method_output_bytes": 9437184}, manifest["resources"])
        self.assertNotIn("oracle_trace_for_case", manifest)

    def test_resource_approval_preserves_authorized_scope_and_pending_translation(self):
        approval_path = PACKAGE / "RESOURCE_APPROVAL_20261021.json"
        self.assertTrue(approval_path.is_file(), "missing approved resource provenance")
        approval = json.loads(approval_path.read_text())
        self.assertEqual(600, approval["approved_values"]["wall_seconds"])
        self.assertEqual("per_slot", approval["approved_wall_scope"])
        self.assertEqual("sandbox_lifecycle_through_image_cleanup",
                         approval["runner_wall_scope"])
        self.assertEqual("PENDING_SCOPE_RESOLUTION", approval["wall_mapping_status"])
        self.assertFalse(approval["formal_80_slot_execution_authorized"])
        self.assertEqual("均批准按照建议执行，并行执行三个研究任务的下一步吧",
                         approval["user_approval_quote"])

    def test_runner_blocks_before_creating_output_or_starting_a_method(self):
        runner = load_runner()
        with tempfile.TemporaryDirectory() as temp:
            output_root = Path(temp) / "returns"
            report = runner.run_task(PACKAGE / "TASK_MANIFEST.json", "synthetic-blocked", output_root)
            self.assertEqual("BLOCKED", report["task_status"])
            self.assertEqual("NOT_EVALUATED", report["research_acceptance"])
            self.assertEqual(0, report["method_start_requests"])
            self.assertEqual(0, report["method_invocations_started"])
            self.assertFalse(output_root.exists())

    def test_oracle_case_labels_live_only_in_scorer_sidecar(self):
        bindings = json.loads((PACKAGE / "CASE_BINDINGS.json").read_text())
        pair_inputs = json.loads((PACKAGE / "PAIR_METHOD_INPUTS.json").read_text())
        case_map = json.loads((PACKAGE / "scorer_source/ORACLE_CASE_MAP.json").read_text())
        self.assertNotIn("oracle_trace_for_case", bindings)
        self.assertEqual(set(bindings["opaque_case_ids"].values()),
                         {case["case_id"] for case in pair_inputs["cases"]})
        self.assertEqual(set(bindings["opaque_case_ids"].values()),
                         set(case_map["oracle_trace_for_case"]))
        self.assertNotIn("I1_NO_INFO_CONTINUING", json.dumps(pair_inputs))
        self.assertNotIn("I2_NO_INFO_NEW", json.dumps(pair_inputs))

    def test_all_published_schemas_are_parseable_json(self):
        schemas = sorted((PACKAGE / "schemas").glob("*.schema.json"))
        self.assertEqual(7, len(schemas))
        for path in schemas:
            with self.subTest(schema=path.name):
                schema = json.loads(path.read_text())
                self.assertEqual("object", schema["type"])
                self.assertTrue(schema.get("$schema", "").endswith("2020-12/schema"))


if __name__ == "__main__":
    unittest.main()
