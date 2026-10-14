import importlib.util
from pathlib import Path
import unittest


PACKAGE = Path(__file__).resolve().parents[1]


def load_pair_inputs():
    module_path = PACKAGE / "pair_inputs.py"
    if not module_path.is_file():
        raise AssertionError("missing feature: frozen A/B/C/D pair construction is not implemented")
    spec = importlib.util.spec_from_file_location("pcg_pair_inputs", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture_public_input():
    rows = [
        {"id": name, "asset": "A" if index < 2 else "B", "task": "J",
         "source_time": index, "alarm": True, "boundary_evidence": []}
        for index, name in enumerate(("a", "b", "c", "d", "e"))
    ]
    traces = []
    for name in ("I1_NO_INFO_CONTINUING", "I2_NO_INFO_NEW"):
        traces.append({"id": name, "rows": [dict(row) for row in rows]})
    recovery = {
        "kind": "RECOVERY", "asset": "B", "task": "J",
        "previous_value": "ACTIVE", "value": "RECOVERED",
        "previous_time": 2, "physical_time": 3.5, "known_time": 3.5,
        "quality": "GOOD", "reliability": "QUALIFIED",
        "source_id": "ledger-Q", "acquisition": "context-RECOVERY-ledger-Q",
        "independent_lineage": True,
    }
    traces.append({"id": "I3_RECOVERY", "rows": [
        *[dict(row) for row in rows[:4]],
        {**dict(rows[4]), "boundary_evidence": [recovery]},
    ]})
    return {"version": "synthetic-fixture", "traces": traces}


class PairInputTests(unittest.TestCase):
    def test_ab_are_byte_equivalent_and_cd_only_change_boundary_evidence_at_e(self):
        cases = load_pair_inputs().build_pair_cases(
            fixture_public_input(),
            {"A": "c-1", "B": "c-2", "C": "c-3", "D": "c-4"},
        )
        by_id = {case["case_id"]: case["rows"] for case in cases["cases"]}
        self.assertEqual(by_id["c-1"], by_id["c-2"])
        for case_id in ("c-3", "c-4"):
            self.assertEqual(by_id["c-2"][:4], by_id[case_id][:4])
            base_e = dict(by_id["c-2"][4])
            actual_e = dict(by_id[case_id][4])
            base_e.pop("boundary_evidence", None)
            actual_e.pop("boundary_evidence", None)
            self.assertEqual(base_e, actual_e)
        self.assertEqual("RECOVERY", by_id["c-3"][4]["boundary_evidence"][0]["kind"])
        stale = by_id["c-4"][4]["boundary_evidence"][0]
        self.assertEqual((0, 1, 4), (stale["previous_time"], stale["physical_time"], stale["known_time"]))

    def test_nonidentical_baseline_arms_are_rejected(self):
        public = fixture_public_input()
        public["traces"][1]["rows"][0]["alarm"] = False
        with self.assertRaisesRegex(ValueError, "A/B method-visible input mismatch"):
            load_pair_inputs().build_pair_cases(
                public, {"A": "c-1", "B": "c-2", "C": "c-3", "D": "c-4"}
            )


if __name__ == "__main__":
    unittest.main()
