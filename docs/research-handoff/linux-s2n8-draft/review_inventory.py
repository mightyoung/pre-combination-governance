"""Static text inventory only: never import package code or launch child processes."""
import argparse,ast,hashlib,json
from pathlib import Path

def loads(raw):
    def pairs(xs):
        d={}
        for k,v in xs:
            if k in d:raise ValueError('duplicate JSON key')
            d[k]=v
        return d
    def invalid(s):raise ValueError('nonfinite JSON literal')
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=invalid)

def main():
    a=argparse.ArgumentParser();a.add_argument('--package',required=True);a.add_argument('--manifest-sha256',required=True);a.add_argument('--summary');args=a.parse_args()
    package=Path(args.package).resolve();raw=(package/'MANIFEST.json').read_bytes();digest=hashlib.sha256(raw).hexdigest()
    if digest!=args.manifest_sha256:raise ValueError('manifest identity mismatch')
    m=loads(raw)
    if m.get('execution_authorized') is not False or m.get('linux_qualified') is not False:raise ValueError('static authority changed')
    found=set();total=0;syntax=0
    for row in m['files']:
        rel=Path(row['path'])
        if rel.is_absolute() or '..' in rel.parts or row['path'] in found or rel.as_posix()!=row['path']:raise ValueError('unsafe/duplicate relative path')
        p=package/rel
        if p.is_symlink() or not p.is_file() or not p.resolve().is_relative_to(package):raise ValueError('missing/nonregular path')
        data=p.read_bytes()
        if len(data)!=row['bytes'] or hashlib.sha256(data).hexdigest()!=row['sha256']:raise ValueError('artifact identity mismatch')
        if p.suffix not in ('.py','.json','.md'):raise ValueError('text extension not allowlisted')
        text=data.decode('utf-8')
        for forbidden in ('/Users/','/private/tmp/','source_thread_id','Sentinel_','BEGIN PRIVATE KEY','BEGIN RSA PRIVATE KEY'):
            if forbidden in text:raise ValueError('private material marker')
        if p.suffix=='.json':loads(data)
        if p.suffix=='.py':ast.parse(text);syntax+=1
        found.add(row['path']);total+=len(data)
    actual={p.relative_to(package).as_posix() for p in package.rglob('*') if p.is_file()}
    if actual!=found|{'MANIFEST.json'}:raise ValueError('unlisted/missing artifact')
    if len(found)!=m['file_count'] or total!=m['total_bytes_excluding_manifest']:raise ValueError('inventory totals mismatch')
    protocol=loads((package/'protocol.json').read_bytes());schedule=loads((package/'schedule.json').read_bytes())
    if protocol['execution_authorized'] is not False or protocol['entrypoint'] is not None or protocol['linux_qualification_executed'] is not False:raise ValueError('execution route unexpectedly present')
    rows=schedule['streams']
    if len(rows)!=2 or [r['method'] for r in rows]!=['ES-Rebuild','Proposed-current-stream'] or any(r['cell']!='S2-N8' or r['phase']!='warmup' or r['checkpoint_responses']!=3 for r in rows):raise ValueError('schedule scope changed')
    result={'status':'STATIC_TEXT_INVENTORY_VALIDATED','manifest_sha256':digest,'listed_files':len(found),'bytes_excluding_manifest':total,'Python_AST_parsed':syntax,'scientific_imports':0,'qualification_actors':0,'scientific_workers':0,'linux_runtime_qualified':False,'execution_authorized':False,'unexecuted':['dependency imports','Linux isolation/resource qualification','worker semantics','timing','cleanup after real processes']}
    text=json.dumps(result,indent=2,sort_keys=True)+'\n';print(text,end='')
    if args.summary:Path(args.summary).write_text('## Static draft inventory only\n\n```json\n'+text+'```\n')
if __name__=='__main__':main()
