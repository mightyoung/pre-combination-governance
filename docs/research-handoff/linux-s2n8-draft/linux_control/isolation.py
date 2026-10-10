"""No namespace fallback. Exact readonly mounts and bootstrap FD only."""
from pathlib import Path
from model import Blocked,canonical,digest

ENV={'PATH':'/nonexistent','PYTHONDONTWRITEBYTECODE':'1','PYTHONNOUSERSITE':'1','OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1','NUMEXPR_NUM_THREADS':'1'}

def profile(package,control,lock,lock_path,fixture):
    package=Path(package).resolve();control=Path(control).resolve();fixture=Path(fixture).resolve()
    mounts=[{'source':str(package/'tools'),'target':'/pkg/tools'},{'source':str(package/'vendor'),'target':'/pkg/vendor'},{'source':str(package/'protocol.json'),'target':'/pkg/protocol.json'},{'source':str(package/'MANIFEST.json'),'target':'/pkg/MANIFEST.json'},{'source':str(control),'target':'/control'},{'source':str(Path(lock_path).resolve()),'target':'/run/runtime-lock.json'},{'source':str(fixture/'allowed.txt'),'target':'/fixture/allowed.txt'}]
    for p in lock['mount_roots']:mounts.append({'source':p,'target':p})
    for row in lock.get('mount_aliases',[]):
        if not any(Path(row['source']).is_relative_to(Path(p)) or row['source']==p for p in lock['mount_roots']) or row['target'] in ('/','/pkg','/control','/proc','/dev'):raise Blocked('UNREVIEWED_RUNTIME_ALIAS')
        mounts.append(row)
    return {'schema_version':'pcg-linux-profile.v1','namespace_flags':['--unshare-all','--die-with-parent','--new-session','--cap-drop','ALL','--clearenv'],'readonly_mounts':mounts,'symlinks':[{'target':'/fixture/outside.txt','path':'/fixture/link'}],'proc':'/proc','dev':'/dev','seccomp':'x86_64-fork-network-write-denial; final entry additionally denies execve','environment':ENV,'worker_reference_sidecar_input_mounts':False}

def command(spec,lock,bootstrap_fd,filter_fd):
    argv=[lock['bwrap'],*spec['namespace_flags'],'--proc','/proc','--dev','/dev']
    # Bind only explicit targets. No --bind, tmpfs home, broad host root or writable temp.
    for row in spec['readonly_mounts']:argv+=['--ro-bind',row['source'],row['target']]
    for row in spec['symlinks']:argv+=['--symlink',row['target'],row['path']]
    argv+=['--remount-ro','/dev','--remount-ro','/proc','--remount-ro','/']
    for k,v in ENV.items():argv+=['--setenv',k,v]
    argv+=['--chdir','/control','--seccomp',str(filter_fd),'--preserve-fds',str(max(bootstrap_fd,filter_fd)-2),'--',lock['python'],'-I','-S','-B','/control/entry.py','--bootstrap-fd',str(bootstrap_fd)]
    return argv
