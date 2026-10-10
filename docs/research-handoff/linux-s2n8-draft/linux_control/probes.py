"""Exactly sixteen fresh slots. Receipts arise only after observed case checks."""
import os,secrets,socket,time
from pathlib import Path
from model import Blocked,LIMITS,canonical,digest,loads
from seccomp import bytes_filter,sealed_fd
from isolation import command

SLOTS=[
 {'slot':1,'mode':'read','isolated':False,'checks':['read_positive'],'exit':0},
 {'slot':2,'mode':'read','isolated':True,'checks':['read_positive'],'exit':0},
 {'slot':3,'mode':'read','isolated':True,'checks':['outside_read_denied'],'exit':77,'errno':[2,13]},
 {'slot':4,'mode':'write','isolated':True,'checks':['source_write_denied'],'exit':77,'errno':[1,30]},
 {'slot':5,'mode':'write','isolated':True,'checks':['outside_write_denied'],'exit':77,'errno':[1,2,30]},
 {'slot':6,'mode':'symlink','isolated':True,'checks':['symlink_escape_denied'],'exit':77,'errno':[2,13]},
 {'slot':7,'mode':'loopback','isolated':False,'checks':['loopback_live_positive'],'exit':0},
 {'slot':8,'mode':'loopback','isolated':True,'checks':['loopback_denied'],'exit':77,'errno':[1]},
 {'slot':9,'mode':'fork','isolated':False,'checks':['fork_positive'],'exit':0},
 {'slot':10,'mode':'fork','isolated':True,'checks':['fork_denied'],'exit':77,'errno':[1]},
 {'slot':11,'implementation_status':'BLOCKED_REQUIRES_INDEPENDENT_WATCHDOG','mode':'term','isolated':False,'checks':['term_resistant_child_cleanup','watchdog_group_cleanup'],'exit':-9},
 {'slot':12,'mode':'cpu','isolated':True,'checks':['cpu_positive'],'exit':0},
 {'slot':13,'mode':'cpu','isolated':True,'checks':['cpu_aggregation','cpu_stop'],'exit':-15},
 {'slot':14,'mode':'rss','isolated':True,'checks':['single_rss_stop','aggregate_rss_stop'],'exit':-15},
 {'slot':15,'mode':'output','isolated':True,'checks':['output_limit'],'exit':-15},
 {'slot':16,'mode':'deadline','isolated':True,'checks':['global_deadline'],'exit':-15},
]

def fixtures(out):
    root=Path(out)/'fixtures';root.mkdir();nonce=secrets.token_hex(24)
    for name in ['allowed.txt','outside.txt']:(root/name).write_text(nonce)
    (root/'link').symlink_to(root/'outside.txt')
    return root,nonce

def frames(raw,nonce):
    result=[]
    for line in raw.splitlines():
        if line.startswith('{'):
            f=loads(line)
            if f.get('nonce')!=nonce:raise Blocked('ACTOR_NONCE_MISMATCH')
            result.append(f)
    return result

def validate(row,result,nonce,*,approved_run_id=None,approved_bindings=None):
    if row.get('implementation_status','') .startswith('BLOCKED_'):raise Blocked('QUALIFICATION_SLOT_NOT_IMPLEMENTED')
    f=frames(result['stdout'],nonce);events={x['event']:x for x in f}
    if 'ready' not in events or result['exit_code']!=row['exit'] or not result['cleanup']['cleanup_complete']:raise Blocked('SLOT_EXIT_READINESS_OR_CLEANUP_FAILED')
    if 'errno' in row:
        if events.get('denied',{}).get('errno') not in row['errno'] or result['failure'] is not None:raise Blocked('LINUX_DENIAL_EVIDENCE_FAILED')
    elif row['slot'] in (1,2,7):
        if events.get('result',{}).get('value')!=nonce or result['failure'] is not None:raise Blocked('POSITIVE_CONTROL_FAILED')
    elif row['slot']==9:
        if events.get('fork_result',{}).get('children')!=1 or events['fork_result']['wait_status']!=0:raise Blocked('FORK_POSITIVE_FAILED')
    elif row['slot']==11:
        if events.get('child_ready',{}).get('children')!=1 or 'WALL_SECONDS_STOP' not in result['stop_reasons']:raise Blocked('TERM_RESISTANT_LIFECYCLE_PROOF_FAILED')
    elif row['slot']==12:
        if 'cpu_done' not in events or result['waited_child_CPU_seconds']<=0:raise Blocked('WAITED_CPU_POSITIVE_FAILED')
    else:
        expected={13:'CPU_SECONDS_STOP',14:'SINGLE_RSS_BYTES_STOP',15:'OUTPUT_BYTES_STOP',16:'WALL_SECONDS_STOP'}[row['slot']]
        if expected not in result['stop_reasons']:raise Blocked('LOW_THRESHOLD_STOP_NOT_OBSERVED')
        if row['slot']==14 and 'AGGREGATE_RSS_BYTES_STOP' not in result['stop_reasons']:raise Blocked('AGGREGATE_RSS_NOT_OBSERVED')
        if row['slot']==13:
            from containment import require_approved_backend
            from cpu_evidence import check_reaped_cpu_evidence
            backend=require_approved_backend(approved_run_id=approved_run_id,approved_bindings=approved_bindings)
            from auth import verify_signature
            receipt=backend.authenticated_reaped_cpu_receipt(fixture_nonce=nonce,reaped_slot=12,current_slot=13)
            evidence=verify_signature(receipt,backend.approved_guard_public_key)
            summary=check_reaped_cpu_evidence(evidence,expected_scope_id=backend.scope_id,expected_child_identity=backend.previous_actor_identity,expected_fixture_nonce=nonce,expected_run_id=approved_run_id,expected_bindings=approved_bindings)
            result['cpu_accounting_evidence_receipt']=receipt
            result['cpu_accounting_consistency']=summary
    return f

def run_all(ledger,lock,control,spec,bootstrap_common,approval,bindings,sign,fixture,nonce):
    phase=ledger.sample();documents=[];indices=[];covered=set();listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(1);listener.setblocking(False);port=listener.getsockname()[1];connections=[]
    def tick():
        try:c,_=listener.accept();c.setblocking(False);connections.append([c,bytearray()])
        except BlockingIOError:pass
        for c,b in connections:
            if c.fileno()<0:continue
            try:
                raw=c.recv(128)
                if raw:b.extend(raw)
                if b.endswith(b'\n'):
                    if bytes(b)!=nonce.encode()+b'\n':raise Blocked('LOOPBACK_NONCE_MISMATCH')
                    c.send(nonce.encode());c.close()
            except BlockingIOError:pass
    try:
        for row in SLOTS:
            s=ledger.check()
            if s['wall_seconds']-phase['wall_seconds']>=45 or s['cpu_seconds']-phase['cpu_seconds']>=8 or s['output_bytes']-phase['output_bytes']>=1048576:raise Blocked('PROBE_PHASE_SUBLIMIT')
            args={'mode':row['mode'],'nonce':nonce,'port':port,'CPU_target':.02 if row['slot']==12 else .15}
            args['path']=('/fixture/' if row['isolated'] else str(fixture)+'/')+('link' if row['slot']==6 else 'outside.txt' if row['slot'] in (3,5) else 'allowed.txt')
            if row['slot']==4:args['path']='/pkg/tools/worker.py'
            cap=sign({'kind':'probe','run_id':approval['run_id'],'bindings':bindings,'slot':row['slot'],'isolated':row['isolated'],'arguments':args,'origin_monotonic':ledger.origin,'deadline_monotonic':ledger.origin+114})
            blob=dict(bootstrap_common,capability=cap,runtime_lock_path='/run/runtime-lock.json' if row['isolated'] else bootstrap_common['runtime_lock_path']);fd=sealed_fd(canonical(blob));filter_fd=None
            if row['isolated']:
                filter_fd=sealed_fd(bytes_filter());argv=command(spec,lock,fd,filter_fd);fds=(fd,filter_fd)
            else:
                argv=[lock['python'],'-I','-S','-B',str(control/'entry.py'),'--bootstrap-fd',str(fd)];fds=(fd,)
            ready_base=[None];before=ledger.sample()
            def lowered(current,stdout):
                # Readiness first; no guessed import-RSS baseline. Same production reasons().
                if ready_base[0] is None and b'"event":"ready"' in stdout:ready_base[0]=dict(current)
                limits={'wall_seconds':min(ledger.origin+114,ledger.origin+phase['wall_seconds']+45)-ledger.origin,'cpu_seconds':min(55,phase['cpu_seconds']+8),'output_bytes':min(10223616,phase['output_bytes']+1048576)}
                if ready_base[0] is not None:
                    b=ready_base[0]
                    if row['slot'] in (11,16):limits['wall_seconds']=min(limits['wall_seconds'],b['wall_seconds']+.2)
                    if row['slot']==13:limits['cpu_seconds']=min(limits['cpu_seconds'],b['cpu_seconds']+.03)
                    if row['slot']==14:
                        limits['single_rss_bytes']=b['single_rss_bytes']+4194304;limits['aggregate_rss_bytes']=b['aggregate_rss_bytes']+4194304
                    if row['slot']==15:limits['output_bytes']=min(limits['output_bytes'],before['output_bytes']+16384)
                return limits
            try:result=ledger.child(argv,fds=fds,wall_cap=2,limits_callback=lowered,tick=tick,input_bytes=b'go\n',start_on_ready=True)
            finally:
                os.close(fd)
                if filter_fd is not None:os.close(filter_fd)
            observed=validate(row,result,nonce,approved_run_id=approval['run_id'],approved_bindings=bindings)
            if any((fixture/name).read_text()!=nonce for name in ('allowed.txt','outside.txt')):raise Blocked('SYNTHETIC_FIXTURE_CHANGED')
            payload={'kind':'probe_receipt','run_id':approval['run_id'],'bindings':bindings,'slot':row['slot'],'status':'PASSED','covered_checks':row['checks'],'cleanup_complete':True,'observation':result,'actor_frames':observed,'origin_monotonic':ledger.origin,'deadline_monotonic':ledger.origin+120}
            receipt=sign(payload);ledger.record('probe-'+str(row['slot']).zfill(2)+'.json',receipt);documents.append(receipt);indices.append({'slot':row['slot'],'covered_checks':row['checks'],'sha256':digest(canonical(receipt))});covered.update(row['checks'])
        q=sign({'kind':'qualification','run_id':approval['run_id'],'bindings':bindings,'status':'PASSED','covered_checks':sorted(covered),'probe_receipts':indices,'origin_monotonic':ledger.origin,'deadline_monotonic':ledger.origin+120});ledger.record('qualification.json',q);return q,documents
    finally:
        for c,_ in connections:c.close()
        listener.close()
