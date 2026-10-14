"""5 pure boundary tests. Prepared; not executed. No process/sandbox actions."""
import unittest
from resource_contract import may_launch, stop_reason


class SupervisorContractTests(unittest.TestCase):
    def test_next_phase_would_exceed_call_budget(self):
        self.assertFalse(may_launch(1, 20, 138, 103))

    def test_reserved_live_cpu_blocks_launch(self):
        self.assertFalse(may_launch(1, 57, 0, 0))

    def test_active_wall_reserves_cleanup_time(self):
        self.assertFalse(may_launch(100, 10, 0, 0))

    def test_output_threshold_stops_before_nominal_ten_mib(self):
        self.assertEqual(stop_reason(1, 10, 0, 9 * 1024 * 1024 + 1, [100]), 'output')

    def test_missing_rss_monitor_is_not_zero_memory(self):
        self.assertEqual(stop_reason(1, 10, 0, 0, []), 'monitor_unavailable')


if __name__ == '__main__':
    unittest.main()
