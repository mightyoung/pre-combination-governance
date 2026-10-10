"""Closed Linux control metadata. Importing this module launches nothing."""
import hashlib,json,re
from pathlib import Path

class Blocked(RuntimeError):
    pass

LIMITS={'wall_seconds':120,'cpu_seconds':60,'worker_wall_seconds':25,'single_rss_bytes':536870912,'aggregate_rss_bytes':2147483648,'output_bytes':10485760,'active_wall_seconds':114,'active_cpu_seconds':55,'active_single_rss_bytes':503316480,'active_aggregate_rss_bytes':1879048192,'active_output_bytes':10223616,'cleanup_offset_seconds':118,'probe_wall_seconds':45,'probe_cpu_seconds':8,'probe_output_bytes':1048576,'fork_cpu_reserve_seconds':2,'maximum_actors':16,'maximum_control_children':2,'maximum_workers':2,'maximum_checkpoints':6}
FAIL_CODES={'preflight':72,'runtime':73,'approval':74,'qualification':75,'science':76,'cleanup':77,'internal':78}
SHA=re.compile(r'^[0-9a-f]{64}$')
RUN_ID=re.compile(r'^[a-zA-Z0-9_-]{1,64}$')

def canonical(v):
    return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def loads(raw):
    def pairs(xs):
        d={}
        for k,v in xs:
            if k in d:raise Blocked('DUPLICATE_JSON_KEY')
            d[k]=v
        return d
    def bad(s):raise Blocked('NONFINITE_JSON')
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=bad)

def inventory(base,manifest_name='MANIFEST.json'):
    base=Path(base).resolve();raw=(base/manifest_name).read_bytes();m=loads(raw);seen=set()
    for row in m['files']:
        rel=Path(row['path'])
        if rel.is_absolute() or '..' in rel.parts or rel.as_posix()!=row['path'] or row['path'] in seen:raise Blocked('UNSAFE_INVENTORY_PATH')
        p=base/rel
        if p.is_symlink() or not p.is_file() or not p.resolve().is_relative_to(base):raise Blocked('UNSAFE_INVENTORY_FILE')
        data=p.read_bytes()
        if len(data)!=row['bytes'] or digest(data)!=row['sha256']:raise Blocked('INVENTORY_HASH_MISMATCH')
        seen.add(row['path'])
    actual={p.relative_to(base).as_posix() for p in base.rglob('*') if p.is_file()}
    if actual!=seen|{manifest_name} or any(p.is_symlink() for p in base.rglob('*')):raise Blocked('UNLISTED_OR_SYMLINK_FILE')
    return digest(raw),m

def signed_body(doc):
    if set(doc)!= {'payload','signature'}:raise Blocked('SIGNATURE_ENVELOPE_SHAPE')
    if not isinstance(doc['payload'],dict) or not isinstance(doc['signature'],str):raise Blocked('SIGNATURE_ENVELOPE_TYPES')
    return doc['payload']
