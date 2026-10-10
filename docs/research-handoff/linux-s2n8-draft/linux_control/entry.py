"""The only supported scientific entry: signed qualification before research import."""
import argparse,os,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from model import Blocked,canonical,digest,inventory,loads


def main():
    from readiness import require_hard_containment
    try:require_hard_containment()
    except Blocked as exc:
        print(str(exc),file=sys.stderr);raise SystemExit(72)
    p=argparse.ArgumentParser();p.add_argument('--bootstrap-fd',type=int,required=True);a=p.parse_args()
    with os.fdopen(a.bootstrap_fd,'rb') as f:raw=f.read(1048577)
    if len(raw)>1048576:raise Blocked('BOOTSTRAP_TOO_LARGE')
    b=loads(raw);control=Path(__file__).resolve().parent
    control_hash,_=inventory(control,'CONTROL-MANIFEST.json')
    bindings=b['bindings']
    if control_hash!=bindings['control_manifest_sha256']:raise Blocked('CONTROL_BINDING_MISMATCH')
    from runtime import verify,enable_locked_sites
    runtime_hash,lock=verify(b['runtime_lock_path']);enable_locked_sites(lock)
    if runtime_hash!=bindings['runtime_binding_sha256']:raise Blocked('RUNTIME_BINDING_MISMATCH')
    policy=loads((control/'policy.json').read_bytes())
    from auth import verify_approval,verify_capability,verify_qualification
    approval=verify_approval(b['approval'],policy,bindings)
    kind=b['capability']['payload'].get('kind')
    cap=verify_capability(b['capability'],approval,bindings,kind)
    if kind=='probe':
        from probes import SLOTS
        slot=cap.get('slot')
        if type(slot) is not int or not 1<=slot<=16:raise Blocked('UNRECOGNIZED_PROBE_SLOT')
        row=SLOTS[slot-1]
        if cap.get('isolated') is not row['isolated'] or cap['arguments']['mode']!=row['mode']:raise Blocked('PROBE_ROLE_MISMATCH')
        if row['isolated']:
            from seccomp import install_final
            install_final()
        from actor import run
        raise SystemExit(run(cap['arguments']))
    if kind!='scientific_worker':raise Blocked('CAPABILITY_NOT_SCIENTIFIC')
    if cap.get('isolated') is not True:raise Blocked('WORKER_MUST_BE_ISOLATED')
    if cap.get('stream_index') not in (1,2) or cap.get('method')!=['ES-Rebuild','Proposed-current-stream'][cap['stream_index']-1]:raise Blocked('WORKER_SLOT_OR_ORDER_MISMATCH')
    q=verify_qualification(b['qualification'],approval,bindings,b['probe_receipts'])
    import jsonschema
    jsonschema.Draft202012Validator(loads((control/'qualification.schema.json').read_bytes())).validate(b['qualification'])
    if cap.get('qualification_sha256')!=digest(canonical(b['qualification'])):raise Blocked('WORKER_QUALIFICATION_BINDING_MISMATCH')
    package=Path('/pkg')
    if digest((package/'MANIFEST.json').read_bytes())!=bindings['package_manifest_sha256']:raise Blocked('PACKAGE_BINDING_MISMATCH')
    manifest=loads((package/'MANIFEST.json').read_bytes())
    for row in manifest['files']:
        if row['path'].startswith(('tools/','vendor/')):
            data=(package/row['path']).read_bytes()
            if len(data)!=row['bytes'] or digest(data)!=row['sha256']:raise Blocked('SCIENTIFIC_CODE_CHANGED')
    protocol=loads((package/'protocol.json').read_bytes())
    if protocol['execution_authorized'] is not False:raise Blocked('PACKAGE_CANNOT_GRANT_EXECUTION')
    # Gate replacement affects authorization only; scientific module bytes remain unchanged.
    sys.path.insert(0,str(package/'tools'))
    import contracts
    def qualified_gate(package_arg,permit_arg):
        if Path(package_arg)!=package or permit_arg!='SESSION_CAPABILITY_ONLY':raise Blocked('STATIC_PERMIT_ROUTE_REJECTED')
        verify_capability(b['capability'],approval,bindings,'scientific_worker')
        verify_qualification(b['qualification'],approval,bindings,b['probe_receipts'])
        return {'authorization_status':'SIGNED_LINUX_QUALIFIED_WORKER','package_manifest_sha256':bindings['package_manifest_sha256']}
    contracts.gate=qualified_gate
    from seccomp import install_final
    install_final()
    import runpy
    sys.argv=['worker.py','--package','/pkg','--permit','SESSION_CAPABILITY_ONLY','--method',cap['method'],'--observed']
    runpy.run_path('/pkg/tools/worker.py',run_name='__main__')

if __name__=='__main__':main()
