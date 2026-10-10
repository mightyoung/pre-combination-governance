"""TESTS WRITTEN, NOT RUN in this static-only submission. No live actor launches."""
import json,time,unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from model import Blocked,LIMITS,loads,canonical
from auth import verify_approval,verify_capability,verify_qualification,REQUIRED
from budget import Ledger
from probes import SLOTS,validate

class StaticNegativeContracts(unittest.TestCase):
    def test_unprovisioned_policy_rejects_static_fake_permit_before_crypto(self):
        fake={'authorization_status':'EXPLICIT_EXECUTION_APPROVED','maximum_workers':2,'maximum_checkpoint_responses':6,'wall_seconds':120,'cpu_seconds':60}
        with self.assertRaisesRegex(Blocked,'TRUST_POLICY_UNPROVISIONED'):verify_approval(fake,{'status':'UNPROVISIONED_BLOCKED'}, {})
    def test_duplicate_json_rejected(self):
        with self.assertRaises(Blocked):loads('{"status":"PASSED","status":"FAILED"}')
    def test_exact_slot_count_and_fixed_numbering(self):
        self.assertEqual([s['slot'] for s in SLOTS],list(range(1,17)))
        self.assertEqual(set().union(*(set(s['checks']) for s in SLOTS)),REQUIRED)
        self.assertEqual([s['slot'] for s in SLOTS if not s['isolated']],[1,7,9,11])
    def test_unsigned_PASSED_does_not_make_qualification(self):
        with self.assertRaises(Blocked):verify_qualification({'payload':{'status':'PASSED'},'signature':''},{'session_public_key':None,'run_id':'x'},{},[])
    def test_incomplete_cleanup_rejects_apparent_success(self):
        r={'stdout':'{"event":"ready","nonce":"x"}\n{"event":"result","nonce":"x","value":"x"}\n','exit_code':0,'failure':None,'cleanup':{'cleanup_complete':False}}
        with self.assertRaises(Blocked):validate(SLOTS[0],r,'x')
    def test_missing_actor_readiness_cannot_accept_bwrap_denial(self):
        r={'stdout':'','exit_code':77,'failure':None,'cleanup':{'cleanup_complete':True}}
        with self.assertRaises(Blocked):validate(SLOTS[2],r,'x')
    def test_non_Linux_denial_code_rejected(self):
        r={'stdout':'{"event":"ready","nonce":"x"}\n{"event":"denied","nonce":"x","errno":99}\n','exit_code':77,'failure':None,'cleanup':{'cleanup_complete':True}}
        with self.assertRaises(Blocked):validate(SLOTS[2],r,'x')
    def test_no_CPU_positive_without_waited_usage(self):
        r={'stdout':'{"event":"ready","nonce":"x"}\n{"event":"cpu_done","nonce":"x"}\n','exit_code':0,'waited_child_CPU_seconds':0,'failure':None,'cleanup':{'cleanup_complete':True}}
        with self.assertRaises(Blocked):validate(SLOTS[11],r,'x')
    def test_RSS_requires_single_and_aggregate_stop(self):
        r={'stdout':'{"event":"ready","nonce":"x"}\n','exit_code':-15,'stop_reasons':['SINGLE_RSS_BYTES_STOP'],'cleanup':{'cleanup_complete':True}}
        with self.assertRaises(Blocked):validate(SLOTS[13],r,'x')
    def test_soft_stops_preserve_cleanup_reserve(self):
        base={'wall_seconds':0,'cpu_seconds':2,'single_rss_bytes':0,'aggregate_rss_bytes':0,'output_bytes':0}
        for key,value in [('wall_seconds',114),('cpu_seconds',55),('single_rss_bytes',503316480),('aggregate_rss_bytes',1879048192),('output_bytes',10223616)]:
            s=dict(base);s[key]=value;self.assertIn(key.upper()+'_STOP',Ledger.reasons(s))
    def test_shared_limits_no_probe_reset_or_larger_budget(self):
        self.assertEqual(LIMITS['cpu_seconds'],60);self.assertEqual(LIMITS['wall_seconds'],120)
        self.assertLessEqual(LIMITS['probe_cpu_seconds']+LIMITS['fork_cpu_reserve_seconds'],LIMITS['cpu_seconds'])
    def test_global_deadline_production_predicate(self):
        s={'wall_seconds':.3,'cpu_seconds':2,'single_rss_bytes':0,'aggregate_rss_bytes':0,'output_bytes':0}
        self.assertIn('WALL_SECONDS_STOP',Ledger.reasons(s,{'wall_seconds':.2}))
    def test_each_probe_explicit_expected_exit(self):
        self.assertTrue(all(type(s['exit']) is int for s in SLOTS))
        self.assertEqual(SLOTS[10]['exit'],-9)
    def test_scientific_entrypoint_checks_chain_before_runpy(self):
        text=(Path(__file__).resolve().parents[1]/'entry.py').read_text()
        self.assertLess(text.index("q=verify_qualification"),text.index("runpy.run_path"))
        self.assertIn('STATIC_PERMIT_ROUTE_REJECTED',text)
    def test_runtime_default_cannot_qualify(self):
        d=json.loads((Path(__file__).resolve().parents[1]/'runtime-lock.json').read_text())
        self.assertEqual(d['status'],'UNRESOLVED_BLOCKED');self.assertEqual(d['files'],[])
    def test_raw_worker_boundary_documented(self):
        text=(Path(__file__).resolve().parents[1]/'policy.json').read_text()
        self.assertIn('arbitrary host owner',text)

if __name__=='__main__':unittest.main()
