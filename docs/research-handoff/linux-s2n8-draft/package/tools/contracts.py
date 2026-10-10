"""Wire/hash contract. Pure data functions; no evaluated imports."""
import hashlib,json,math
from pathlib import Path

def canonical(v):return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')
def digest(raw):return hashlib.sha256(raw).hexdigest()
def loads(raw):
    def pairs(items):
        d={}
        for k,v in items:
            if k in d:raise ValueError('duplicate JSON key')
            d[k]=v
        return d
    def invalid(v):raise ValueError('nonfinite JSON literal '+v)
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=invalid)
def projection(result):
    return {k:result[k] for k in ('status','failure_code','risk_interval','bpa','action_state','active_contribution_count')}
def gate(package,permit_path):
    package=Path(package).resolve();permit=loads(Path(permit_path).read_bytes())
    manifest_raw=(package/'MANIFEST.json').read_bytes()
    protocol=loads((package/'protocol.json').read_bytes())
    assert protocol['execution_authorized'] is False
    expected={'authorization_status':'EXPLICIT_EXECUTION_APPROVED','package_manifest_sha256':digest(manifest_raw),'source_commit':protocol['source_commit'],'maximum_workers':2,'maximum_checkpoint_responses':6,'wall_seconds':120,'worker_wall_seconds':25,'cpu_seconds':60,'A_A_authorized':False,'algorithm_changes_authorized':False}
    for key,val in expected.items():
        if type(permit.get(key)) is not type(val) or permit.get(key)!=val:raise PermissionError('execution permit missing or mismatched: '+key)
    return permit

def check_science(result,reference):
    s=projection(result);r=reference['public'];tol=1e-12
    if s['status']!=r['status'] or s['failure_code']!=r['failure_code'] or s['action_state']!=r['action_state'] or s['active_contribution_count']!=r['active_count']:raise ValueError('INVALID_SEMANTICS categorical fields')
    if s['bpa']['frame']!=['RISK','NOT_RISK'] or s['bpa']['focal_sets']!=[['RISK'],['RISK','NOT_RISK']]:raise ValueError('INVALID_SEMANTICS BPA structure')
    exact=r['lower_exact'];lower=int(exact['numerator'])/int(exact['denominator'])
    if not isinstance(s['risk_interval'],list) or len(s['risk_interval'])!=2 or not isinstance(s['bpa']['masses'],list) or len(s['bpa']['masses'])!=2:raise ValueError('INVALID_SEMANTICS individual numeric shapes')
    actual=[*s['risk_interval'],*s['bpa']['masses']];expected=[lower,1.,lower,1.-lower]
    if len(actual)!=4 or any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in actual):raise ValueError('INVALID_SEMANTICS nonfinite/numeric shape')
    errors=[abs(a-b) for a,b in zip(actual,expected)]
    if any(x>tol for x in errors):raise ValueError('INVALID_SEMANTICS numeric tolerance')
    return {'maximum_absolute_error':max(errors),'science_sha256':digest(canonical(s)),'science':s}


def expected_visits(sequence,n,checkpoint):
    if checkpoint==0:return n*(n+1)//2
    if sequence=='S3' and checkpoint==3:return (n+2)*(n+3)//2+n+3
    if sequence=='S4':return [3*n+6,n+4,n+5][checkpoint-1]
    return n+checkpoint

def check_observer(row,response,checkpoint):
    if row['phase']!='warmup':
        if response.get('observer') is not None:raise ValueError('unexpected measurement observer')
        return
    obs=response.get('observer')
    if not isinstance(obs,dict):raise ValueError('missing warmup observer')
    expected=(expected_visits(row['sequence'],row['N'],checkpoint) if row['method']=='Proposed-current-stream' else (0 if checkpoint==0 else row['N']+(checkpoint+2 if row['sequence']=='S4' else checkpoint)))
    if obs.get('counts',{}).get('history_evaluation_visits',0)!=expected:raise ValueError('OBSERVER_HISTORY_COUNT_MISMATCH')
    if row['method']=='ES-Rebuild' and checkpoint and obs['counts'].get('sorting_entries')!=expected:raise ValueError('OBSERVER_SORTING_COUNT_MISMATCH')

def verify_qualification(package,qualification_path,approval,profile_sha256,runtime_sha256,required):
    """Bind real probe receipts; presence of a PASSED string alone is insufficient."""
    from pathlib import Path
    import jsonschema
    b=Path(package);path=Path(qualification_path).resolve();raw=path.read_bytes();q=loads(raw)
    jsonschema.Draft202012Validator(loads((b/'contracts/qualification.schema.json').read_bytes())).validate(q)
    if approval.get('qualification_sha256')!=digest(raw) or q['package_manifest_sha256']!=approval['package_manifest_sha256'] or q['profile_sha256']!=profile_sha256 or q['runtime_binding_sha256']!=runtime_sha256:raise PermissionError('qualification binding mismatch')
    if not required.issubset(set(q['covered_checks'])):raise PermissionError('missing required boundary check')
    proved=set()
    for item in q['probe_receipts']:
        receipt_path=(path.parent/item['path']).resolve()
        if not receipt_path.is_relative_to(path.parent) or receipt_path.suffix!='.json':raise PermissionError('probe receipt must be scoped JSON')
        receipt_raw=receipt_path.read_bytes()
        if digest(receipt_raw)!=item['sha256']:raise PermissionError('probe receipt hash mismatch')
        receipt=loads(receipt_raw)
        if receipt.get('status')!='PASSED' or set(receipt.get('covered_checks',[]))!=set(item['covered_checks']) or receipt.get('package_manifest_sha256')!=q['package_manifest_sha256'] or receipt.get('profile_sha256')!=q['profile_sha256'] or receipt.get('runtime_binding_sha256')!=q['runtime_binding_sha256']:raise PermissionError('probe receipt evidence mismatch')
        proved.update(item['covered_checks'])
    if not required.issubset(proved):raise PermissionError('missing bound probe evidence')
    return q
