"""Verify a separately reviewed Linux lock before loading third-party code."""
import hashlib,os,platform,sys
from pathlib import Path
from model import Blocked,digest,loads

EXPECTED={'cryptography':'46.0.5','jsonschema':'4.26.0','psutil':'7.2.2'}

def verify(lock_path,guard=None):
    if guard:guard()
    with Path(lock_path).open('rb') as f:raw=f.read(4194305)
    if len(raw)>4194304:raise Blocked('RUNTIME_LOCK_TOO_LARGE')
    doc=loads(raw)
    if sys.platform!='linux' or platform.machine()!='x86_64':raise Blocked('UNSUPPORTED_PLATFORM_REQUIRES_REVIEW')
    if doc.get('status')!='FROZEN_LINUX' or not doc.get('files') or not doc.get('mount_roots'):raise Blocked('LINUX_RUNTIME_UNPROVISIONED')
    if doc.get('python_version')!='3.12.10' or sys.version_info[:3]!=(3,12,10):raise Blocked('PYTHON_VERSION_MISMATCH')
    if doc.get('dependencies')!=EXPECTED:raise Blocked('DEPENDENCY_LOCK_MISMATCH')
    roots=[]
    for value in doc['mount_roots']:
        p=Path(value)
        if not p.is_absolute() or str(p) in ('/','/home','/root','/usr','/tmp') or p.is_symlink() or p.resolve()!=p:raise Blocked('OVERBROAD_OR_ALIAS_RUNTIME_ROOT')
        roots.append(p)
    seen=set()
    for row in doc['files']:
        if guard:guard()
        p=Path(row['path'])
        if str(p) in seen or p.is_symlink() or not p.is_file() or not any(p.resolve().is_relative_to(r) or p.resolve()==r for r in roots):raise Blocked('RUNTIME_FILE_OUTSIDE_LOCK')
        if p.suffix in ('.pem','.key','.env') or p.name=='.env':raise Blocked('PRIVATE_RUNTIME_ARTIFACT_FORBIDDEN')
        h=hashlib.sha256();size=0
        with p.open('rb') as f:
            while True:
                if guard:guard()
                chunk=f.read(1048576)
                if not chunk:break
                size+=len(chunk);h.update(chunk)
                if size>row['bytes']:raise Blocked('RUNTIME_SIZE_MISMATCH')
        if size!=row['bytes'] or h.hexdigest()!=row['sha256']:raise Blocked('RUNTIME_HASH_MISMATCH')
        seen.add(str(p))
    # Entire selected roots are fingerprinted; no unbound pyc/extension/metadata can load.
    actual=set()
    for r in roots:
        for p in ([r] if r.is_file() else r.rglob('*')):
            if guard:guard()
            if p.is_symlink():raise Blocked('RUNTIME_SYMLINK_UNREVIEWED')
            if p.is_file():actual.add(str(p))
    if actual!=seen:raise Blocked('INCOMPLETE_RUNTIME_ROOT_FINGERPRINT')
    for key in ('python','bwrap'):
        p=Path(doc[key])
        if str(p) not in seen or not os.access(p,os.X_OK):raise Blocked('UNLOCKED_EXECUTABLE')
    if Path(doc['python']).resolve()!=Path(sys.executable).resolve():raise Blocked('INTERPRETER_LOCK_MISMATCH')
    sites=doc.get('site_roots',[])
    if not sites or not all(str(Path(s)) in [str(r) for r in roots] for s in sites):raise Blocked('SITE_ROOTS_NOT_FROZEN')
    return digest(raw),doc

def enable_locked_sites(doc):
    # -S prevents .pth/sitecustomize; only reviewed full-tree paths added explicitly.
    for p in reversed(doc['site_roots']):sys.path.insert(0,p)
    import importlib.metadata
    for name,version in EXPECTED.items():
        if importlib.metadata.version(name)!=version:raise Blocked('INSTALLED_DEPENDENCY_VERSION_MISMATCH')
    # All third-party transitive files are already included in the full-tree lock.
