"""Gated stream adapter. Do not run without a separately approved permit."""
import argparse,sys,time
from pathlib import Path
from contracts import canonical,loads,gate,digest,projection

def event_projection(a):
    return {'event_id':a['action_id'],'order':a['order'],'message_id':a['message_id'],'version':a['version'],'root_id':a['root_id'],'support':a['support'],'reliability':a['reliability']}
def control_projection(a):
    d={'control_id':a['action_id'],'kind':a['op'],'order':a['order'],'roots':a['roots']}
    for key in ('canonical_root','replacement_root'):
        if key in a:d[key]=a[key]
    return d

def proposed_projection(engine):
    # Preserve native projection work, including native audit fields.
    from rfb.methods.lifecycle_engine import project_snapshot
    s=project_snapshot(engine.snapshot)
    if s['status']=='SAFE_HALT':raise ValueError('unexpected SAFE_HALT')
    lower=round(float(s['risk_score']),12)
    return {'status':'SUCCEEDED','failure_code':None,'risk_interval':[lower,1.0],'bpa':{'frame':['RISK','NOT_RISK'],'focal_sets':[['RISK'],['RISK','NOT_RISK']],'masses':[lower,round(1.-lower,12)]},'action_state':'ACT' if lower>=.7 else 'REVIEW','active_contribution_count':len(s['audit_classes']),'duplicate_count':s['duplicate_count']}

def main():
    p=argparse.ArgumentParser();p.add_argument('--package',required=True);p.add_argument('--permit',required=True);p.add_argument('--method',choices=['Proposed-current-stream','ES-Rebuild'],required=True);p.add_argument('--observed',action='store_true');a=p.parse_args()
    b=Path(a.package).resolve();gate(b,a.permit)
    variant='observed' if a.observed else 'original'
    sys.path.insert(0,str(b/'vendor'/variant/'risk-fusion-bench/src'))
    if a.observed:
        import pcg_observer
    # Evaluated modules are imported only below a successful execution gate.
    if a.method=='Proposed-current-stream':
        from rfb.methods.lifecycle_engine import LifecycleEngine
    else:
        from rfb.research.mme_baselines import evaluate_baseline
    events=[];controls=[];engine=None;cap=None;lastorder=0;seen_actions=set();checkpoint=0;initial=None
    for raw in iter(lambda: sys.stdin.buffer.readline(65537),b''):
        if len(raw)>65536 or not raw.endswith(b'\n'):raise ValueError('FRAME_SIZE_OR_TRUNCATION')
        started=time.perf_counter_ns();request=loads(raw)
        if a.observed:pcg_observer.reset()
        if request['kind']=='initialize':
            if initial is not None:raise ValueError('duplicate initialization')
            cap=request['method_cap']
            if cap!={'max_active_contributions':128,'max_contribution_budget':128}:raise ValueError('cap mismatch')
            if a.method=='Proposed-current-stream':engine=LifecycleEngine(**cap)
            actions=request['initial_actions']
        elif request['kind']=='checkpoint':
            if initial is None or request['checkpoint_id']!=checkpoint+1 or checkpoint>=3:raise ValueError('checkpoint sequence')
            actions=request['delta']
        else:raise ValueError('invalid request')
        for action in actions:
            if action['order']<=lastorder or action['action_id'] in seen_actions:raise ValueError('nonmonotonic order/action id')
            lastorder=action['order'];seen_actions.add(action['action_id'])
            if action['op']=='INITIALIZE':events.append(event_projection(action))
            else:controls.append(control_projection(action))
            if engine is not None:engine.apply(action)
        if len(events)+len(controls)>37:raise ValueError('history bound')
        if request['kind']=='initialize':
            initial={'history_length':len(actions),'load_ns':time.perf_counter_ns()-started,'observer':pcg_observer.snapshot() if a.observed else None}
            if engine is not None:initial.update({'revision':engine.snapshot.revision,'ledger_length':len(engine.snapshot.ledger),'active_count':len(engine.snapshot.classes)})
            else:initial.update({'revision':None,'ledger_length':None,'active_count':None})
            response={'kind':'initialized',**initial}
        else:
            checkpoint+=1
            result=proposed_projection(engine) if engine is not None else evaluate_baseline('ES-Rebuild',{'events':events,'controls':controls},cap)
            science=projection(result);science_bytes=canonical(science)
            finished=time.perf_counter_ns()
            response={'kind':'checkpoint','checkpoint_id':checkpoint,'total_update_ns':finished-started,'science':science,'science_sha256':digest(science_bytes),'duplicate_count':result['duplicate_count'],'history_length':len(events)+len(controls),'observer':pcg_observer.snapshot() if a.observed else None,'measurement_class':'INSTRUMENTED_WARMUP_ONLY' if a.observed else 'UNINSTRUMENTED_TOTAL'}
        payload=canonical(response)+b'\n'
        if len(payload)>65536:raise ValueError('RESPONSE_SIZE')
        sys.stdout.buffer.write(payload);sys.stdout.buffer.flush()
    if checkpoint!=3:raise ValueError('incomplete stream')
if __name__=='__main__':main()
