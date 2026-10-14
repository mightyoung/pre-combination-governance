import importlib.util
from pathlib import Path
import unittest


PACKAGE = Path(__file__).resolve().parents[1]


def load_slot_worker():
    module_path = PACKAGE / "frozen_source" / "runtime" / "slot_worker.py"
    if not module_path.is_file():
        raise AssertionError("missing feature: one-prefix isolated slot adapter is not implemented")
    spec = importlib.util.spec_from_file_location("pcg_pair_slot_worker", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SlotWorkerTests(unittest.TestCase):
    def test_adapter_passes_only_method_prefix_and_prior_public_state(self):
        adapter = load_slot_worker()
        observed = []
        prefix = [{"id": "a", "alarm": True}]
        prior = {"cards": {}, "risk": "UNKNOWN", "priority": "REVIEW"}
        result = adapter.handle({"method": "M1", "prefix": prefix, "old": prior},
                                lambda rows, method, old: observed.append((rows, method, old)) or {"ok": True})
        self.assertEqual({"ok": True}, result)
        self.assertEqual([(prefix, "M1", prior)], observed)

    def test_case_labels_future_rows_and_oracle_fields_are_rejected(self):
        adapter = load_slot_worker()
        base = {"method": "M1", "prefix": [{"id": "a", "alarm": True}], "old": {}}
        for forbidden in ("case_id", "oracle", "truth", "future_rows", "trace"):
            payload = dict(base)
            payload[forbidden] = []
            with self.subTest(field=forbidden), self.assertRaisesRegex(ValueError, "exactly"):
                adapter.handle(payload, lambda *_: {})


if __name__ == "__main__":
    unittest.main()
