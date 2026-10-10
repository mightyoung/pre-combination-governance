"""Consistency checks for authenticated backend CPU evidence, never authorization.

Caller must obtain the evidence and expected identities from an approved kernel
backend. Self-labelled JSON and increasing psutil CPU counters are not evidence.
"""
from model import Blocked,SHA,RUN_ID

SNAPSHOT_KEYS={'sequence','kernel_cpu_ns','waited_cpu_ns','reaped_children','charged_cpu_ns'}
EVIDENCE_KEYS={'schema_version','fixture_nonce','run_id','bindings','reaped_slot','current_slot','scope_id','child_identity','child_wait_cpu_ns','cpu_usage_source','completed_cpu_source','child_exit_confirmed','scope_membership_complete','reaped_child_cleanup_complete','before_child','after_reap','after_next_actor'}

def _natural(value):
    return type(value) is int and value>=0

def check_reaped_cpu_evidence(evidence,*,expected_scope_id,expected_child_identity,expected_fixture_nonce,expected_run_id,expected_bindings):
    if not isinstance(evidence,dict) or set(evidence)!=EVIDENCE_KEYS:raise Blocked('REAPED_CPU_EVIDENCE_MISSING_OR_SHAPE')
    if evidence['schema_version']!='pcg-kernel-reaped-cpu.v1' or not isinstance(expected_scope_id,str) or not expected_scope_id or evidence['scope_id']!=expected_scope_id:raise Blocked('CPU_SCOPE_IDENTITY_MISMATCH')
    if not isinstance(expected_fixture_nonce,str) or not expected_fixture_nonce or evidence['fixture_nonce']!=expected_fixture_nonce:raise Blocked('CPU_FIXTURE_NONCE_MISMATCH')
    binding_keys={'package_manifest_sha256','control_manifest_sha256','runtime_binding_sha256','profile_sha256','probe_plan_sha256'}
    bindings=evidence['bindings']
    if not isinstance(expected_run_id,str) or not RUN_ID.fullmatch(expected_run_id) or evidence['run_id']!=expected_run_id:raise Blocked('CPU_APPROVED_RUN_MISMATCH')
    if not isinstance(bindings,dict) or set(bindings)!=binding_keys or not all(isinstance(v,str) and SHA.fullmatch(v) for v in bindings.values()) or bindings!=expected_bindings:raise Blocked('CPU_APPROVED_ARTIFACT_BINDINGS_MISMATCH')
    if type(evidence['reaped_slot']) is not int or type(evidence['current_slot']) is not int or (evidence['reaped_slot'],evidence['current_slot'])!=(12,13):raise Blocked('CPU_SLOT12_TO_13_BINDING_REQUIRED')
    identity=evidence['child_identity']
    if not isinstance(identity,dict) or set(identity)!={'pid','start_time_ticks'} or any(type(identity[k]) is not int or identity[k]<=0 for k in identity) or identity!=expected_child_identity:raise Blocked('REAPED_CHILD_IDENTITY_MISMATCH')
    if evidence['cpu_usage_source']!='kernel_scope_cumulative' or evidence['completed_cpu_source']!='wait4_ledger':raise Blocked('CPU_PROVENANCE_NOT_APPROVED_KERNEL_AND_WAIT4')
    if any(evidence[k] is not True for k in ('child_exit_confirmed','scope_membership_complete','reaped_child_cleanup_complete')):raise Blocked('CPU_MEMBERSHIP_REAP_OR_CLEANUP_UNCONFIRMED')
    child=evidence['child_wait_cpu_ns']
    if not _natural(child) or child==0:raise Blocked('CONTROLLED_CHILD_CPU_NOT_MEASURED')
    names=('before_child','after_reap','after_next_actor');snapshots=[]
    for name in names:
        snapshot=evidence[name]
        if not isinstance(snapshot,dict) or set(snapshot)!=SNAPSHOT_KEYS or not all(_natural(v) for v in snapshot.values()):raise Blocked('CPU_SNAPSHOT_SHAPE_OR_TYPE')
        if snapshot['charged_cpu_ns']<snapshot['kernel_cpu_ns']:raise Blocked('KERNEL_CPU_NOT_FULLY_CHARGED')
        snapshots.append(snapshot)
    before,reaped,next_actor=snapshots
    if not before['sequence']<reaped['sequence']<next_actor['sequence']:raise Blocked('CPU_SNAPSHOT_ORDER')
    for field in SNAPSHOT_KEYS-{'sequence'}:
        if not before[field]<=reaped[field]<=next_actor[field]:raise Blocked('CPU_COUNTER_RESET_OR_REAP_CREDIT_LOSS')
    # Exactly one identified controlled child is reaped across this interval.
    if reaped['reaped_children']!=before['reaped_children']+1 or reaped['waited_cpu_ns']!=before['waited_cpu_ns']+child:raise Blocked('IDENTIFIED_CHILD_WAIT_CREDIT_NOT_RETAINED')
    if reaped['kernel_cpu_ns']-before['kernel_cpu_ns']<child or reaped['charged_cpu_ns']-before['charged_cpu_ns']<child:raise Blocked('REAPED_CPU_OMITTED_FROM_CUMULATIVE_TOTAL')
    return {'scope_id':expected_scope_id,'child_identity':identity,'retained_wait_cpu_ns':child,'last_kernel_cpu_ns':next_actor['kernel_cpu_ns'],'consistency_only':True}
