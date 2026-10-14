import importlib.util
import os
from pathlib import Path
import unittest


PACKAGE = Path(__file__).resolve().parents[1]


def load_preflight():
    module_path = PACKAGE / "preflight.py"
    if not module_path.is_file():
        raise AssertionError("missing feature: resource preflight is not implemented")
    spec = importlib.util.spec_from_file_location("pcg_pair_preflight", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ResourcePreregistrationTests(unittest.TestCase):
    def test_missing_limits_block_even_if_environment_variables_claim_values(self):
        old = {key: os.environ.get(key) for key in (
            "PCG_CPU_QUOTA_MILLIS", "PCG_WALL_SECONDS", "PCG_MEMORY_BYTES",
            "PCG_PIDS_LIMIT", "PCG_MAX_OUTPUT_BYTES")}
        try:
            os.environ.update({
                "PCG_CPU_QUOTA_MILLIS": "1000",
                "PCG_WALL_SECONDS": "120",
                "PCG_MEMORY_BYTES": "268435456",
                "PCG_PIDS_LIMIT": "16",
                "PCG_MAX_OUTPUT_BYTES": "9437184",
            })
            manifest = {
                "task_id": "PCG-IDENTIFIABILITY-PAIRED-CPU-001",
                "resources": {
                    "cpu_quota_millis": 1000,
                    "wall_seconds": None,
                    "memory_bytes": None,
                    "pids_limit": None,
                    "max_method_output_bytes": None,
                },
            }
            profile = load_preflight().validate_resource_profile(manifest)
            self.assertEqual("BLOCKED", profile.status)
            self.assertEqual(
                {"wall_seconds", "memory_bytes", "pids_limit", "max_method_output_bytes"},
                set(profile.missing_fields),
            )
        finally:
            for key, value in old.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
