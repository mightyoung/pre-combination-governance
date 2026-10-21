"""Synthetic manifest mutations; never start Docker or research methods."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE))
import runner


class ExecutionPinInventoryTests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((PACKAGE / 'TASK_MANIFEST.json').read_text())

    def test_each_execution_pin_is_mandatory(self):
        for relative in self.manifest['execution_file_hashes']:
            with self.subTest(relative=relative):
                changed = copy.deepcopy(self.manifest)
                del changed['execution_file_hashes'][relative]
                self.assertTrue(runner._valid_manifest(changed),
                                'missing execution pin accepted: ' + relative)

    def test_extra_execution_pin_is_rejected(self):
        self.manifest['execution_file_hashes']['../outside.py'] = 'a' * 64
        self.assertTrue(runner._valid_manifest(self.manifest))

    def test_complete_inventory_remains_structurally_valid(self):
        self.assertEqual([], runner._valid_manifest(self.manifest))

    def test_missing_slot_worker_pin_blocks_before_docker_or_output(self):
        self.manifest['resources'].update(wall_seconds=120, memory_bytes=268435456,
                                         pids_limit=16, max_method_output_bytes=9437184)
        self.manifest['resource_profile_status'] = 'PRE_REGISTERED'
        del self.manifest['execution_file_hashes']['frozen_source/runtime/slot_worker.py']
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'manifest.json'
            path.write_text(json.dumps(self.manifest))
            output = Path(temp) / 'returns'
            with mock.patch.object(runner, 'DockerSession') as docker:
                result = runner.run_task(path, 'synthetic-missing-pin', output)
            self.assertEqual('BLOCKED', result['task_status'])
            self.assertIn('execution source pin inventory', result['stop_reason'])
            self.assertEqual(0, result['method_invocations_started'])
            self.assertFalse(output.exists())
            docker.assert_not_called()


if __name__ == '__main__':
    unittest.main()
