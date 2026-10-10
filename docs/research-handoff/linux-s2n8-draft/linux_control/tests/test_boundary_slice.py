"""Boundary slice tests WRITTEN NOT RUN; synthetic mappings prove no qualification."""
import copy,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from model import Blocked
from isolation import runtime_mounts,overlaps,RUNTIME_ALIAS_TARGETS
from cpu_evidence import check_reaped_cpu_evidence
from containment import require_approved_backend
from probes import SLOTS,validate

class MountTargets(unittest.TestCase):
    def lock(self,target):
        return {'mount_roots':['/opt/pcg-runtime/lib'],'mount_aliases':[{'source':'/opt/pcg-runtime/lib/ld.so','target':target}]}
    def test_only_source_defined_runtime_targets_accepted(self):
        for target in RUNTIME_ALIAS_TARGETS:
            self.assertEqual(runtime_mounts(self.lock(target),['/control','/pkg/tools','/run/runtime-lock.json'])[-1]['target'],target)
    def test_protected_files_and_directories_rejected(self):
        for target in ('/control/entry.py','/pkg/tools/worker.py','/run/runtime-lock.json','/control','/pkg','/run','/fixture/link','/proc','/dev','/'):
            with self.subTest(target=target),self.assertRaises(Blocked):runtime_mounts(self.lock(target),[])
    def test_normalized_protected_overlay_rejected(self):
        for target in ('/lib/../control/entry.py','/control//entry.py','/pkg/vendor/../tools/worker.py','/run/a/../runtime-lock.json'):
            with self.subTest(target=target),self.assertRaisesRegex(Blocked,'OVERLAP'):runtime_mounts(self.lock(target),[])
    def test_unapproved_runtime_alias_target_rejected(self):
        with self.assertRaisesRegex(Blocked,'NOT_WHITELISTED'):runtime_mounts(self.lock('/usr/lib'),[])
    def test_direct_runtime_root_cannot_overlay_control(self):
        for root in ('/control/entry.py','/pkg/tools/worker.py','/run/runtime-lock.json'):
            with self.subTest(root=root),self.assertRaisesRegex(Blocked,'OVERLAP'):runtime_mounts({'mount_roots':[root],'mount_aliases':[]},[])
    def test_duplicate_runtime_target_rejected(self):
        lock=self.lock('/lib/x86_64-linux-gnu');lock['mount_aliases']*=2
        with self.assertRaisesRegex(Blocked,'OVERLAP'):runtime_mounts(lock,[])
    def test_normalized_ancestor_and_descendant_conflicts_rejected(self):
        with self.assertRaisesRegex(Blocked,'OVERLAP'):runtime_mounts(self.lock('/lib/x86_64-linux-gnu'),['/lib/x86_64-linux-gnu/existing.so'])
        with self.assertRaisesRegex(Blocked,'OVERLAP'):runtime_mounts(self.lock('/lib64/ld-linux-x86-64.so.2'),['/lib64/./'])
    def test_component_boundaries_are_not_string_prefixes(self):
        self.assertFalse(overlaps('/control','/control-other/entry.py'));self.assertTrue(overlaps('/control','/a/../control/entry.py'))
    def test_noncanonical_source_and_runtime_alias_spelling_rejected(self):
        lock=self.lock('/lib/./x86_64-linux-gnu')
        with self.assertRaisesRegex(Blocked,'NONCANONICAL'):runtime_mounts(lock,[])
        lock=self.lock('/lib/x86_64-linux-gnu');lock['mount_aliases'][0]['source']='/opt/pcg-runtime/lib/a/../ld.so'
        with self.assertRaisesRegex(Blocked,'NONCANONICAL'):runtime_mounts(lock,[])
    def test_runtime_lock_cannot_extend_source_whitelist(self):
        lock=self.lock('/control/entry.py');lock['allowed_targets']=['/control/entry.py']
        with self.assertRaises(Blocked):runtime_mounts(lock,[])
    def test_alias_source_outside_frozen_runtime_roots_rejected(self):
        lock=self.lock('/lib/x86_64-linux-gnu');lock['mount_aliases'][0]['source']='/outside/ld.so'
        with self.assertRaisesRegex(Blocked,'SOURCE_OUTSIDE_LOCK'):runtime_mounts(lock,[])

class ReapedCPU(unittest.TestCase):
    def evidence(self):
        return {'schema_version':'pcg-kernel-reaped-cpu.v1','fixture_nonce':'synthetic-nonce','run_id':'synthetic-test-run','bindings':{k:'0'*64 for k in ('package_manifest_sha256','control_manifest_sha256','runtime_binding_sha256','profile_sha256','probe_plan_sha256')},'reaped_slot':12,'current_slot':13,'scope_id':'synthetic-test-scope','child_identity':{'pid':123,'start_time_ticks':456},'child_wait_cpu_ns':20000000,'cpu_usage_source':'kernel_scope_cumulative','completed_cpu_source':'wait4_ledger','child_exit_confirmed':True,'scope_membership_complete':True,'reaped_child_cleanup_complete':True,'before_child':{'sequence':10,'kernel_cpu_ns':100000000,'waited_cpu_ns':0,'reaped_children':0,'charged_cpu_ns':2100000000},'after_reap':{'sequence':11,'kernel_cpu_ns':130000000,'waited_cpu_ns':20000000,'reaped_children':1,'charged_cpu_ns':2130000000},'after_next_actor':{'sequence':12,'kernel_cpu_ns':150000000,'waited_cpu_ns':20000000,'reaped_children':1,'charged_cpu_ns':2150000000}}
    def check(self,e):
        return check_reaped_cpu_evidence(e,expected_scope_id='synthetic-test-scope',expected_child_identity={'pid':123,'start_time_ticks':456},expected_fixture_nonce='synthetic-nonce',expected_run_id='synthetic-test-run',expected_bindings=self.evidence()['bindings'])
    def test_consistent_synthetic_data_is_only_consistency(self):
        self.assertEqual(self.check(self.evidence())['consistency_only'],True)
    def test_missing_evidence_and_CPU_increase_alone_rejected(self):
        for e in (None,{'cpu_seconds':2.1},{'before_cpu_seconds':2,'after_cpu_seconds':3}):
            with self.assertRaises(Blocked):self.check(e)
    def test_counter_reset_or_lost_reap_credit_rejected(self):
        for key in ('kernel_cpu_ns','charged_cpu_ns','waited_cpu_ns','reaped_children'):
            e=self.evidence();e['after_next_actor'][key]=0
            with self.subTest(key=key),self.assertRaises(Blocked):self.check(e)
    def test_reaped_child_and_scope_identity_bound(self):
        for field,value in (('fixture_nonce','other-nonce'),('scope_id','another-scope'),('child_identity',{'pid':123,'start_time_ticks':457})):
            e=self.evidence();e[field]=value
            with self.assertRaises(Blocked):self.check(e)
    def test_approved_run_artifact_and_slot_context_bound(self):
        for field,value in (('run_id','another-run'),('bindings',{}),('reaped_slot',11),('current_slot',14)):
            e=self.evidence();e[field]=value
            with self.subTest(field=field),self.assertRaises(Blocked):self.check(e)
    def test_wait4_credit_and_cumulative_charge_both_required(self):
        for key,value in (('waited_cpu_ns',1),('reaped_children',0),('kernel_cpu_ns',110000000),('charged_cpu_ns',2110000000)):
            e=self.evidence();e['after_reap'][key]=value
            with self.subTest(key=key),self.assertRaises(Blocked):self.check(e)
    def test_unaccounted_kernel_cpu_rejected(self):
        e=self.evidence();e['after_next_actor']['charged_cpu_ns']=149999999
        with self.assertRaisesRegex(Blocked,'NOT_FULLY_CHARGED'):self.check(e)
    def test_unknown_membership_or_cleanup_is_not_pass(self):
        for field in ('child_exit_confirmed','scope_membership_complete','reaped_child_cleanup_complete'):
            e=self.evidence();e[field]=False
            with self.assertRaises(Blocked):self.check(e)
    def test_wrong_provenance_bool_nan_and_reordered_snapshots_rejected(self):
        for field,value in (('cpu_usage_source','psutil'),('child_wait_cpu_ns',True),('child_wait_cpu_ns',float('nan'))):
            e=self.evidence();e[field]=value
            with self.assertRaises(Blocked):self.check(e)
        e=self.evidence();e['after_next_actor']['sequence']=9
        with self.assertRaises(Blocked):self.check(e)
    def test_unapproved_backend_has_no_metadata_enable_route(self):
        with self.assertRaisesRegex(Blocked,'NOT_DELEGATED'):require_approved_backend()
    def test_slot13_increasing_sample_does_not_qualify(self):
        result={'stdout':'{"event":"ready","nonce":"x"}\n','exit_code':-15,'cleanup':{'cleanup_complete':True},'stop_reasons':['CPU_SECONDS_STOP'],'samples':[{'cpu_seconds':2},{'cpu_seconds':3}]}
        with self.assertRaisesRegex(Blocked,'NOT_DELEGATED'):validate(SLOTS[12],result,'x')
    def test_source_guard_precedes_bootstrap_and_inventory_reads(self):
        base=Path(__file__).resolve().parents[1]
        for name,read in (('entry.py','with os.fdopen'),('launcher.py',"inventory(control")):
            text=(base/name).read_text();self.assertLess(text.index('require_hard_containment()'),text.index(read));self.assertLess(text.index('require_hard_containment()'),text.index('p.parse_args()'))

if __name__=='__main__':unittest.main()
