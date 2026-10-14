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
    def test_manifest_keeps_unprovided_resource_limits_blocked(self):
        manifest = json.loads((PACKAGE / "TASK_MANIFEST.json").read_text())
        self.assertEqual("BLOCKED_MISSING_VALUES", manifest["resource_profile_status"])
        self.assertEqual(1000, manifest["resources"]["cpu_quota_millis"])
        for field in ("wall_seconds", "memory_bytes", "pids_limit", "max_method_output_bytes"):
            self.assertIsNone(manifest["resources"][field])
        self.assertNotIn("oracle_trace_for_case", manifest)

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
