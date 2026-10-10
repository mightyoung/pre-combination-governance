"""Source-defined runtime-only targets; namespace mounts cannot shadow control."""
import posixpath
from pathlib import Path,PurePosixPath
from model import Blocked

ENV={'PATH':'/nonexistent','PYTHONDONTWRITEBYTECODE':'1','PYTHONNOUSERSITE':'1','OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1','NUMEXPR_NUM_THREADS':'1'}
# A different already-installed runtime layout requires a new source review.
RUNTIME_ROOT_TARGETS=frozenset({'/opt/pcg-runtime/python','/opt/pcg-runtime/site','/opt/pcg-runtime/lib'})
RUNTIME_ALIAS_TARGETS=frozenset({'/lib/x86_64-linux-gnu','/usr/lib/x86_64-linux-gnu','/lib64/ld-linux-x86-64.so.2'})
PROTECTED_TARGETS=('/control','/pkg','/run','/fixture','/proc','/dev','/home','/root','/tmp')

def normalized_absolute(value):
    if not isinstance(value,str) or not value.startswith('/') or value.startswith('//') or '\x00' in value or '\\' in value:raise Blocked('INVALID_NAMESPACE_PATH')
    return posixpath.normpath(value)

def overlaps(left,right):
    left=PurePosixPath(normalized_absolute(left));right=PurePosixPath(normalized_absolute(right))
    return left==right or left in right.parents or right in left.parents

def runtime_mounts(lock,fixed_targets):
    roots=lock.get('mount_roots',[])
    if not isinstance(roots,list) or not roots:raise Blocked('RUNTIME_ROOTS_MISSING')
    rows=[];occupied=list(fixed_targets)
    def append(source,target,allowed):
        source_normal=normalized_absolute(source);target_normal=normalized_absolute(target)
        # Compare normalized component paths before rejecting spelling/whitelist.
        if any(overlaps(target_normal,p) for p in [*PROTECTED_TARGETS,*occupied]):raise Blocked('RUNTIME_MOUNT_TARGET_OVERLAP')
        if target_normal not in allowed:raise Blocked('RUNTIME_MOUNT_TARGET_NOT_WHITELISTED')
        if source!=source_normal or target!=target_normal:raise Blocked('NONCANONICAL_RUNTIME_MOUNT_PATH')
        rows.append({'source':source_normal,'target':target_normal});occupied.append(target_normal)
    for root in roots:append(root,root,RUNTIME_ROOT_TARGETS)
    for row in lock.get('mount_aliases',[]):
        if not isinstance(row,dict) or set(row)!={'source','target'}:raise Blocked('RUNTIME_ALIAS_SHAPE')
        source=normalized_absolute(row['source'])
        if not any(PurePosixPath(source)==PurePosixPath(r) or PurePosixPath(r) in PurePosixPath(source).parents for r in roots):raise Blocked('RUNTIME_ALIAS_SOURCE_OUTSIDE_LOCK')
        append(row['source'],row['target'],RUNTIME_ALIAS_TARGETS)
    return rows

def profile(package,control,lock,lock_path,fixture):
    package=Path(package).resolve();control=Path(control).resolve();fixture=Path(fixture).resolve()
    mounts=[{'source':str(package/'tools'),'target':'/pkg/tools'},{'source':str(package/'vendor'),'target':'/pkg/vendor'},{'source':str(package/'protocol.json'),'target':'/pkg/protocol.json'},{'source':str(package/'MANIFEST.json'),'target':'/pkg/MANIFEST.json'},{'source':str(control),'target':'/control'},{'source':str(Path(lock_path).resolve()),'target':'/run/runtime-lock.json'},{'source':str(fixture/'allowed.txt'),'target':'/fixture/allowed.txt'}]
    mounts.extend(runtime_mounts(lock,[r['target'] for r in mounts]))
    return {'schema_version':'pcg-linux-profile.v2','namespace_flags':['--unshare-all','--die-with-parent','--new-session','--cap-drop','ALL','--clearenv'],'readonly_mounts':mounts,'symlinks':[{'target':'/fixture/outside.txt','path':'/fixture/link'}],'proc':'/proc','dev':'/dev','seccomp':'x86_64-fork-network-write-denial; final entry additionally denies execve','environment':ENV,'worker_reference_sidecar_input_mounts':False}

def command(spec,lock,bootstrap_fd,filter_fd):
    argv=[lock['bwrap'],*spec['namespace_flags'],'--proc','/proc','--dev','/dev']
    for row in spec['readonly_mounts']:argv+=['--ro-bind',row['source'],row['target']]
    for row in spec['symlinks']:argv+=['--symlink',row['target'],row['path']]
    argv+=['--remount-ro','/dev','--remount-ro','/proc','--remount-ro','/']
    for k,v in ENV.items():argv+=['--setenv',k,v]
    argv+=['--chdir','/control','--seccomp',str(filter_fd),'--preserve-fds',str(max(bootstrap_fd,filter_fd)-2),'--',lock['python'],'-I','-S','-B','/control/entry.py','--bootstrap-fd',str(bootstrap_fd)]
    return argv
