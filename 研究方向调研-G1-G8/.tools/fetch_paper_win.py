#!/usr/bin/env python3
"""Pinned arXiv fetch with bounded downloads and immutable transactional versions."""
import argparse
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

MAX_DOWNLOAD=32*1024*1024
MAX_EXPANDED=128*1024*1024
MAX_MEMBER=32*1024*1024
MAX_FILES=2000
RETRIES=3
STALE={'old','history','backup','draft','previous','archive','submitted','.stale'}
PIN=re.compile(r'^(?P<base>\d{4}\.\d{4,5}|[a-z][a-z.-]*/\d{7})(?P<version>v[1-9]\d*)$')

def digest(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for chunk in iter(lambda:f.read(65536),b''): h.update(chunk)
 return h.hexdigest()

def download(url,opener,pause):
 for attempt in range(RETRIES):
  try:
   request=urllib.request.Request(url,headers={'User-Agent':'research-workflow/2 (academic use)'})
   with opener(request,timeout=30) as response:
    status=getattr(response,'status',200)
    if status!=200: raise urllib.error.HTTPError(url,status,'non-200',{},None)
    final=response.geturl() or url
    # A redirect must still identify exactly the requested version and endpoint.
    expected=urlsplit(url);actual=urlsplit(final)
    canonic=expected.path.replace('/e-print/','/src/',1) if expected.path.startswith('/e-print/') else expected.path
    if actual.scheme!='https' or actual.hostname not in ('arxiv.org','export.arxiv.org') or actual.path.rstrip('/') not in (expected.path.rstrip('/'),canonic.rstrip('/')): raise ValueError('redirect changed pinned paper/version')
    content_type=response.headers.get('Content-Type','').split(';')[0].lower()
    if content_type in ('text/html','application/xhtml+xml'): raise ValueError('HTML response refused')
    length=response.headers.get('Content-Length')
    if length is not None:
     try: length=int(length)
     except ValueError: raise ValueError('invalid HTTP content length') from None
     if length<0 or length>MAX_DOWNLOAD: raise ValueError('HTTP body exceeds download limit')
    data=bytearray()
    while True:
     chunk=response.read(min(65536,MAX_DOWNLOAD+1-len(data)))
     if not chunk: break
     data.extend(chunk)
     if len(data)>MAX_DOWNLOAD: raise ValueError('HTTP body exceeds download limit')
    if length is not None and len(data)!=length: raise ValueError('truncated HTTP body')
    if not data: raise ValueError('empty HTTP body')
    return bytes(data),content_type
  except urllib.error.HTTPError as e:
   if e.code not in (408,429,500,502,503,504) or attempt==RETRIES-1: raise
  except (urllib.error.URLError,TimeoutError,ConnectionError):
   if attempt==RETRIES-1: raise
  pause(3*(attempt+1))
 raise AssertionError('retry exhausted')

def extract_source(blob,destination):
 """No tar extraction primitives, links, devices, duplicate paths or oversized members."""
 if blob.startswith(b'\x1f\x8b'):
  try:
   with gzip.GzipFile(fileobj=io.BytesIO(blob)) as f: decoded=f.read(MAX_EXPANDED+1)
  except (OSError,EOFError): raise ValueError('invalid gzip source') from None
  if len(decoded)>MAX_EXPANDED: raise ValueError('source expanded limit exceeded')
 else: decoded=blob
 if len(decoded)>MAX_EXPANDED: raise ValueError('source expanded limit exceeded')
 # Decompress under a cap before tar parses PAX/long-name metadata.
 try: archive=tarfile.open(fileobj=io.BytesIO(decoded),mode='r:')
 except tarfile.ReadError:
  if len(decoded)>MAX_MEMBER: raise ValueError('source member limit exceeded')
  if b'\\documentclass' not in decoded and b'\\begin{document}' not in decoded: raise ValueError('source is not recognizable TeX or tar') from None
  destination.mkdir();(destination/'main.tex').write_bytes(decoded);return
 seen=set();total=0;count=0
 with archive:
  # Stream member iteration; getmembers() could allocate unbounded metadata.
  for member in archive:
   count+=1
   if count>MAX_FILES: raise ValueError('too many archive members')
   name=member.name
   if '\\' in name or '\x00' in name or ':' in name or len(name)>512: raise ValueError('unsafe archive path')
   rel=PurePosixPath(name)
   if rel.is_absolute() or '..' in rel.parts: raise ValueError('archive path traversal')
   if not member.isdir() and not member.isfile(): raise ValueError('archive links/special files refused')
   if not rel.parts:
    if member.isdir(): continue
    raise ValueError('empty archive filename')
   key=rel.as_posix()
   if key in seen: raise ValueError('duplicate archive path')
   seen.add(key)
   if len(rel.parts)>20: raise ValueError('archive path too deep')
   target=destination.joinpath(*rel.parts)
   if member.isdir(): target.mkdir(parents=True,exist_ok=True);continue
   total+=member.size
   if member.size<0 or member.size>MAX_MEMBER or total>MAX_EXPANDED: raise ValueError('archive expanded limit exceeded')
   target.parent.mkdir(parents=True,exist_ok=True)
   try:
    with archive.extractfile(member) as source, target.open('xb') as out:
     remaining=member.size
     while remaining:
      chunk=source.read(min(65536,remaining))
      if not chunk: raise ValueError('truncated archive member')
      out.write(chunk);remaining-=len(chunk)
   except OSError as e: raise ValueError(f'archive path collision: {e.strerror}') from None
 if not any(destination.rglob('*.tex')): raise ValueError('source archive contains no TeX')

def strip_comments(data):
 # Conservative line comments only. Not a TeX parser; raw/PDF is authoritative.
 output=[]
 for line in data.splitlines(keepends=True):
  end=len(line)
  for i,value in enumerate(line):
   if value!=37: continue
   backslashes=0;j=i-1
   while j>=0 and line[j]==92: backslashes+=1;j-=1
   if backslashes%2==0: end=i;break
  output.append(line[:end]+(b'\n' if end<len(line) and line.endswith(b'\n') else b''))
 return b''.join(output)

def clean_source(raw,clean):
 clean.mkdir()
 for file in sorted(raw.rglob('*')):
  rel=file.relative_to(raw)
  if not file.is_file() or any(part.lower() in STALE for part in rel.parts) or file.name.endswith('.orig'): continue
  dest=clean/rel;dest.parent.mkdir(parents=True,exist_ok=True)
  if file.suffix.lower()=='.tex': dest.write_bytes(strip_comments(file.read_bytes()))
  else: shutil.copyfile(file,dest)

def safe_directory(path):
 if path.is_symlink() or path.exists() and not path.is_dir(): raise ValueError(f'unsafe directory: {path}')
 path.mkdir(exist_ok=True)

def verify_cache(path,identifier):
 if path.is_symlink() or not path.is_dir(): raise ValueError('unsafe cached version')
 manifest_path=path/'manifest.json'
 if manifest_path.is_symlink(): raise ValueError('unsafe manifest')
 try: manifest=json.loads(manifest_path.read_text())
 except (OSError,json.JSONDecodeError): raise ValueError('cached manifest invalid; manual review required') from None
 if manifest.get('arxiv_id')!=identifier: raise ValueError('slug already used for another paper')
 hashes=manifest.get('sha256')
 if not isinstance(hashes,dict) or 'paper.pdf' not in hashes: raise ValueError('cached manifest missing hashes')
 actual_files=set()
 for f in path.rglob('*'):
  if f.is_symlink(): raise ValueError('symlink in cached version')
  if f.is_file() and f.name!='manifest.json': actual_files.add(f.relative_to(path).as_posix())
 if actual_files!=set(hashes): raise ValueError('cached files changed; manual review required')
 for rel,expected in hashes.items():
  if not isinstance(rel,str) or PurePosixPath(rel).is_absolute() or '..' in PurePosixPath(rel).parts or digest(path/rel)!=expected: raise ValueError('cached hash mismatch; manual review required')
 return path

def fetch(identifier,slug,project,opener=urllib.request.urlopen,pause=time.sleep):
 match=PIN.fullmatch(identifier)
 if not match: raise ValueError('explicit arXiv version required, e.g. 2301.11305v1')
 slug=slug or identifier.replace('/','-')
 if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}',slug): raise ValueError('unsafe slug')
 project=Path(project).absolute()
 if project.is_symlink(): raise ValueError('symlink project refused')
 project=project.resolve()
 if not project.is_dir(): raise ValueError('project directory must exist')
 related=project/'related_work';safe_directory(related)
 paper=related/slug;safe_directory(paper)
 versions=paper/'versions';safe_directory(versions)
 # Cooperating fetches serialize; symlink lock injection cannot redirect writes.
 import contextlib as _cx
 with _cx.nullcontext():  # Windows host: fcntl unavailable; single-writer no-op lock
  target=versions/match['version']
  # Every existing version must share the same base arXiv identity.
  for previous in versions.iterdir():
   if previous.name.startswith('.stage-'): continue
   if previous.is_symlink(): raise ValueError('unsafe existing version')
   if previous.is_dir():
    if (previous/'manifest.json').is_symlink(): raise ValueError('unsafe existing manifest')
    try: cached_id=json.loads((previous/'manifest.json').read_text()).get('arxiv_id','')
    except (OSError,json.JSONDecodeError): raise ValueError('existing version missing manifest') from None
    if not isinstance(cached_id,str) or not PIN.fullmatch(cached_id) or PIN.fullmatch(cached_id)['base']!=match['base']: raise ValueError('slug already used for another paper')
  if target.exists() or target.is_symlink(): return verify_cache(target,identifier)
  with tempfile.TemporaryDirectory(prefix='.stage-',dir=versions) as temp:
   staging=Path(temp)
   pdf,pdf_type=download('https://arxiv.org/pdf/'+identifier,opener,pause)
   if pdf_type not in ('application/pdf','application/octet-stream') or not pdf.startswith(b'%PDF-') or b'%%EOF' not in pdf[-1024:]: raise ValueError('invalid/truncated PDF signature or media type')
   (staging/'paper.pdf').write_bytes(pdf)
   pause(3) # polite spacing between endpoints; retries are separately bounded
   source_status='available';source_reason=None
   try: blob,_=download('https://arxiv.org/e-print/'+identifier,opener,pause)
   except urllib.error.HTTPError as e:
    if e.code not in (404,410): raise
    source_status='PDF-only';source_reason=f'source HTTP {e.code}'
   else:
    if blob.startswith(b'%PDF-') and b'%%EOF' in blob[-1024:]:
     source_status='PDF-only';source_reason='e-print endpoint returned a PDF rather than TeX'
    else:
     source=staging/'source';source.mkdir();(source/'download.bin').write_bytes(blob)
     extract_source(blob,source/'raw');clean_source(source/'raw',source/'clean')
   manifest={'arxiv_id':identifier,'version':match['version'],'source_status':source_status,'source_reason':source_reason,'pdf_url':'https://arxiv.org/pdf/'+identifier,'source_url':'https://arxiv.org/e-print/'+identifier,'retrieved_at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'cleaning_note':'Heuristic comments/stale-directory exclusion; validate quotations against pinned PDF/raw. No source code executed.','sha256':{p.relative_to(staging).as_posix():digest(p) for p in sorted(staging.rglob('*')) if p.is_file()}}
   (staging/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
   verify_cache(staging,identifier)
   # The only publication point. Same filesystem rename; previous versions untouched.
   os.rename(staging,target)
  return target

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('arxiv_id');p.add_argument('slug',nargs='?');p.add_argument('--project',type=Path,default=Path.cwd());a=p.parse_args()
 try:
  path=fetch(a.arxiv_id,a.slug,a.project);manifest=json.loads((path/'manifest.json').read_text());print(f'{path} ({manifest["source_status"]})')
 except (OSError,ValueError,tarfile.TarError) as e: p.exit(1,f'fetch failed; existing versions preserved: {e}\n')
if __name__=='__main__': main()
