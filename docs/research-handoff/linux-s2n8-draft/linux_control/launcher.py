"""Static-review candidate: provisioned trust/runtime + fresh16 before two workers."""
import time
ORIGIN=time.monotonic()
import argparse,ctypes,os,resource,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from model import Blocked,LIMITS,FAIL_CODES,canonical,digest,inventory,loads
from runtime import verify,enable_locked_sites
from auth import verify_approval,session_signer,consume,verify_qualification
from budget import Ledger
from probes import fixtures,run_all,SLOTS
from isolation import profile,command
from seccomp import bytes_filter,sealed_fd


def preflight_guard():
    u=resource.getrusage(resource.RUSAGE_SELF)
    if time.monotonic()-ORIGIN>=114 or u.ru_utime+u.ru_stime+2>=55 or (sys.platform=='linux' and u.ru_maxrss*1024>=503316480):raise Blocked('PREFLIGHT_BUDGET_STOP')


def scientific_batch(ledger,package,control,lock,spec,common,approval,bindings,sign,q,receipts):
    sys.path.insert(0,str(package/'tools'))
    import contracts  # Pure-data gates/oracle projection; no scientific module imported here.
    schedule=loads((package/'schedule.json').read_bytes())['streams'];input_raw=(package/'inputs/S2-N8.public.json').read_bytes();data=loads(input_raw);reference=loads((package/'reference/S2-N8.reference.json').read_bytes());result_rows=[]
    if len(schedule)!=2 or [r['method'] for r in schedule]!=['ES-Rebuild','Proposed-current-stream']:raise Blocked('EXACT_TWO_WORKER_SCHEDULE_REQUIRED')
    for row in schedule:
        verify_qualification(q,approval,bindings,receipts);ledger.check()
        cap=sign({'kind':'scientific_worker','run_id':approval['run_id'],'bindings':bindings,'method':row['method'],'stream_index':row['stream_index'],'isolated':True,'qualification_sha256':digest(canonical(q)),'origin_monotonic':ORIGIN,'deadline_monotonic':min(ORIGIN+114,time.monotonic()+25)})
        boot=dict(common,capability=cap,qualification=q,probe_receipts=receipts);fd=sealed_fd(canonical(boot));sf=sealed_fd(bytes_filter());wire=canonical({'kind':'initialize','method_cap':data['method_cap'],'initial_actions':data['initial_actions']})+b'\n'
        for cp in data['checkpoints']:wire+=canonical({'kind':'checkpoint','checkpoint_id':cp['checkpoint_id'],'delta':cp['delta']})+b'\n'
        if len(wire)>1048576:raise Blocked('INPUT_CAP')
        ledger.pending=1048576
        try:result=ledger.child(command(spec,lock,fd,sf),fds=(fd,sf),input_bytes=wire,wall_cap=25)
        finally:os.close(fd);os.close(sf);ledger.pending=0
        ledger.record('stream-'+str(row['stream_index'])+'.json',result)
        if result['failure'] is not None or result['exit_code']!=0 or not result['cleanup']['cleanup_complete']:raise Blocked('WORKER_EXIT_OR_CLEANUP_FAILED')
        responses=[]
        for line in result['stdout'].splitlines():
            if len(line.encode())>65536:raise Blocked('RESPONSE_FRAME_LIMIT')
            responses.append(loads(line))
        if len(responses)!=4 or responses[0].get('kind')!='initialized':raise Blocked('ACK_AND_THREE_CHECKPOINTS_REQUIRED')
        contracts.check_observer(row,responses[0],0)
        for idx,response in enumerate(responses[1:],1):
            if response.get('kind')!='checkpoint' or response.get('checkpoint_id')!=idx:raise Blocked('CHECKPOINT_ORDER')
            saved=contracts.check_science(response['science'],reference['checkpoints'][idx-1]);contracts.check_observer(row,response,idx)
            if response.get('duplicate_count')!=reference['checkpoints'][idx-1]['public']['duplicate_count'] or response.get('science_sha256')!=saved['science_sha256']:raise Blocked('DUPLICATE_OR_SCIENCE_HASH_MISMATCH')
        result_rows.append({'method':row['method'],'ACKs':1,'checkpoints':3})
    return result_rows


def main():
    from readiness import require_hard_containment
    try:require_hard_containment()
    except Blocked as exc:
        print(str(exc),file=sys.stderr);raise SystemExit(72)
    p=argparse.ArgumentParser();p.add_argument('--package',required=True);p.add_argument('--control-manifest-sha256',required=True);p.add_argument('--runtime-lock',required=True);p.add_argument('--signed-approval',required=True);p.add_argument('--session-key-fd',type=int,required=True);p.add_argument('--output-root',required=True);a=p.parse_args()
    control=Path(__file__).resolve().parent;package=Path(a.package).resolve();ledger=None;failure=None;stage='preflight';failure_code=0
    try:
        preflight_guard();control_hash,_=inventory(control,'CONTROL-MANIFEST.json')
        if control_hash!=a.control_manifest_sha256:raise Blocked('REVIEWED_CONTROL_DIGEST_MISMATCH')
        package_hash,_=inventory(package);stage='runtime';runtime_hash,lock=verify(a.runtime_lock,preflight_guard);preflight_guard();enable_locked_sites(lock)
        stage='approval';policy=loads((control/'policy.json').read_bytes());approval_envelope=loads(Path(a.signed_approval).read_bytes());plan_hash=digest(canonical(SLOTS))
        # Profile binds an approved output/run fixture location before actor creation.
        body=approval_envelope.get('payload',{});output_root=Path(a.output_root).resolve();run_id=body.get('run_id','')
        from model import RUN_ID
        if not RUN_ID.fullmatch(run_id):raise Blocked('INVALID_RUN_ID')
        planned_fixture=output_root/run_id/'fixtures';spec=profile(package,control,lock,a.runtime_lock,planned_fixture)
        bindings={'package_manifest_sha256':package_hash,'control_manifest_sha256':control_hash,'runtime_binding_sha256':runtime_hash,'profile_sha256':digest(canonical(spec)),'probe_plan_sha256':plan_hash}
        approval=verify_approval(approval_envelope,policy,bindings);sign=session_signer(a.session_key_fd,approval);out=consume(approval,output_root);ledger=Ledger(ORIGIN,out);ledger.check()
        # Orphan reaping is a required Linux control capability, not optional fallback.
        libc=ctypes.CDLL(None,use_errno=True)
        if libc.prctl(36,1,0,0,0)!=0:raise Blocked('CHILD_SUBREAPER_UNAVAILABLE')
        fixture,nonce=fixtures(out);common={'approval':approval_envelope,'bindings':bindings,'runtime_lock_path':str(Path(a.runtime_lock).resolve())}
        # Same runtime-lock absolute path must be available inside the namespace.
        common_isolated=dict(common,runtime_lock_path='/run/runtime-lock.json')
        # run_all selects host or isolated bootstrap path per slot; no scientific imports.
        stage='qualification';q,receipts=run_all(ledger,lock,control,spec,common,approval,bindings,sign,fixture,nonce)
        verify_qualification(q,approval,bindings,receipts)
        import jsonschema
        jsonschema.Draft202012Validator(loads((control/'qualification.schema.json').read_bytes())).validate(q)
        stage='science';rows=scientific_batch(ledger,package,control,lock,spec,common_isolated,approval,bindings,sign,q,receipts)
        ledger.record('research-result.json',{'status':'COMPLETED_EXPOSED_DEVELOPMENT_ONLY','rows':rows,'ACKs':2,'checkpoint_responses':6})
    except Exception as exc:failure=type(exc).__name__+':'+str(exc)[:512];failure_code=FAIL_CODES[stage]
    finally:
        if ledger is not None:
            cleanup=ledger.cleanup()
            try:sample=ledger.sample()
            except Exception as exc:sample=None;failure=failure or 'FINAL_USAGE_UNKNOWN:'+str(exc)
            if not cleanup['cleanup_complete']:failure=failure or 'CLEANUP_UNCONFIRMED';failure_code=FAIL_CODES['cleanup']
            if sample and (sample['wall_seconds']>=120 or sample['cpu_seconds']>60 or sample['single_rss_bytes']>536870912 or sample['aggregate_rss_bytes']>2147483648 or sample['output_bytes']>10485760):failure=failure or 'FINAL_BUDGET_LIMIT'
            if failure and not failure_code:failure_code=FAIL_CODES['cleanup']
            try:ledger.record('final.json',{'status':'FAILED' if failure else 'COMPLETED','failure':failure,'exit_code':failure_code,'cleanup':cleanup,'last_usage':sample,'peaks':{'CPU_charged':ledger.cpu_high,'single_RSS':ledger.max_rss,'aggregate_RSS':ledger.max_total_rss},'qualification_and_science_not_inferred_from_static_review':True},final=True)
            except Exception as exc:failure=failure or 'FINAL_RECEIPT_NOT_SAVED:'+str(exc)[:512];failure_code=FAIL_CODES['cleanup']
        if failure:
            print(failure,file=sys.stderr);raise SystemExit(failure_code or FAIL_CODES['cleanup'])

if __name__=='__main__':main()
