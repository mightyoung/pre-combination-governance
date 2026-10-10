"""Observation only. Imported only by explicitly instrumented source copies."""
import time
from collections import Counter
_counts=Counter();_stages=Counter();_pending={}
def reset():
    _counts.clear();_stages.clear();_pending.clear()
def count(name,amount=1):
    _counts[name]+=amount
def start(name):
    if name in _pending:raise RuntimeError('overlapping observer stage')
    _pending[name]=time.perf_counter_ns()
def end(name):
    _stages[name]+=time.perf_counter_ns()-_pending.pop(name)
def snapshot():
    if _pending:raise RuntimeError('unfinished observer stage')
    return {'counts':dict(_counts),'exclusive_stage_ns':dict(_stages),'unseparated_stage':'UPDATE_WITH_EMBEDDED_AUDIT','unimplemented_counters':['history_identity_comparisons','contribution_token_visits','class_reads','class_writes','runtime_audit_records','hash_ops'],'measurement_class':'INSTRUMENTED_WARMUP_ONLY'}
