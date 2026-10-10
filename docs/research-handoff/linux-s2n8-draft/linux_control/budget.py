"""One cumulative ledger, owned process identities, bounded output and cleanup."""
import errno,os,resource,selectors,signal,subprocess,time
from pathlib import Path
from model import Blocked,LIMITS,canonical,digest

class Ledger:
    def __init__(self,origin,out):
        import psutil
        self.ps=psutil;self.origin=origin;self.out=Path(out);self.owned={};self.roots={};self.groups=set();self.cpu_high=0.;self.max_rss=0;self.max_total_rss=0;self.pending=0;self.buffers=0;self.faults=[];self.last=None
    def directory_bytes(self):
        total=0
        for p in self.out.rglob('*'):
            if p.is_symlink():
                if p!=self.out/'fixtures/link':raise Blocked('UNEXPECTED_OUTPUT_SYMLINK')
                total+=len(os.readlink(p).encode());continue
            if p.is_file():total+=p.stat().st_size
        return total
    def register(self,p):
        node=self.ps.Process(p.pid);self.owned[p.pid]=node.create_time();self.roots[p.pid]=p;self.groups.add(p.pid)
    def _node(self,pid):
        p=self.ps.Process(pid)
        if p.create_time()!=self.owned[pid]:raise Blocked('OWNED_PID_REUSED')
        return p
    def sample(self):
        live={}
        for pid in list(self.roots):
            try:
                root=self._node(pid)
                for n in [root,*root.children(recursive=True)]:
                    created=n.create_time()
                    if n.pid in self.owned and self.owned[n.pid]!=created:raise Blocked('OWNED_PID_REUSED')
                    self.owned[n.pid]=created;live[n.pid]=n
            except self.ps.NoSuchProcess:pass
            except self.ps.AccessDenied as exc:raise Blocked('OWNED_TREE_ACCESS_DENIED') from exc
        for pid in list(self.owned):
            try:live[pid]=self._node(pid)
            except self.ps.NoSuchProcess:pass
            except self.ps.AccessDenied as exc:raise Blocked('OWNED_PROCESS_ACCESS_DENIED') from exc
        own=resource.getrusage(resource.RUSAGE_SELF);waited=resource.getrusage(resource.RUSAGE_CHILDREN);cpu=own.ru_utime+own.ru_stime+waited.ru_utime+waited.ru_stime;rss=self.ps.Process().memory_info().rss;single=rss
        for pid,n in live.items():
            try:
                t=n.cpu_times();r=n.memory_info().rss;cpu+=t.user+t.system;rss+=r;single=max(single,r)
            except self.ps.NoSuchProcess:pass
            except self.ps.AccessDenied as exc:raise Blocked('OWNED_USAGE_ACCESS_DENIED') from exc
        charged=max(self.cpu_high,cpu+LIMITS['fork_cpu_reserve_seconds']);self.cpu_high=charged;self.max_rss=max(self.max_rss,single);self.max_total_rss=max(self.max_total_rss,rss)
        sample={'wall_seconds':time.monotonic()-self.origin,'observed_cpu_seconds':cpu,'cpu_seconds':charged,'single_rss_bytes':single,'aggregate_rss_bytes':rss,'output_bytes':self.directory_bytes()+self.pending+self.buffers,'origin_monotonic':self.origin};self.last=sample;return sample
    @staticmethod
    def reasons(s,overrides=None):
        thresholds={'wall_seconds':LIMITS['active_wall_seconds'],'cpu_seconds':LIMITS['active_cpu_seconds'],'single_rss_bytes':LIMITS['active_single_rss_bytes'],'aggregate_rss_bytes':LIMITS['active_aggregate_rss_bytes'],'output_bytes':LIMITS['active_output_bytes']}
        if overrides:thresholds.update(overrides)
        return [k.upper()+'_STOP' for k,v in thresholds.items() if s[k]>=v]
    def check(self,overrides=None):
        s=self.sample();reasons=self.reasons(s,overrides)
        if reasons:raise Blocked(','.join(reasons))
        return s
    def record(self,name,value,*,final=False):
        raw=canonical(value)+b'\n'
        if len(raw)>(262144 if final else 1048576):raise Blocked('RECORD_TOO_LARGE')
        # Keep 256KiB reserved for final failure/cleanup receipt; no output reset.
        ceiling=LIMITS['output_bytes'] if final else LIMITS['active_output_bytes']
        if self.directory_bytes()+len(raw)+self.pending+self.buffers>ceiling:raise Blocked('OUTPUT_RECEIPT_RESERVE_STOP')
        path=self.out/name
        if path.exists() or path.parent.resolve()!=self.out.resolve():raise Blocked('RECORD_OVERWRITE_OR_PATH')
        with path.open('xb') as f:f.write(raw)
        return {'path':name,'sha256':digest(raw)}
    def group_members(self,gid):
        result=[]
        try:
            for pid in self.ps.pids():
                try:
                    if os.getpgid(pid)==gid:result.append(self.ps.Process(pid))
                except (ProcessLookupError,self.ps.NoSuchProcess):pass
                except (PermissionError,self.ps.AccessDenied) as exc:raise Blocked('GROUP_ENUMERATION_UNCERTAIN') from exc
        except self.ps.AccessDenied as exc:raise Blocked('GROUP_ENUMERATION_UNCERTAIN') from exc
        return result
    def cleanup(self):
        errors=[]
        try:self.sample()
        except Exception as exc:errors.append(type(exc).__name__+':'+str(exc))
        def signal_owned(sig):
            for pid in list(self.owned):
                try:
                    n=self._node(pid)
                    if n.status()!=self.ps.STATUS_ZOMBIE:os.kill(pid,sig)
                except (ProcessLookupError,self.ps.NoSuchProcess):pass
                except Exception as exc:errors.append(type(exc).__name__+':'+str(exc))
        signal_owned(signal.SIGTERM);grace=min(time.monotonic()+1.,self.origin+LIMITS['cleanup_offset_seconds'])
        while time.monotonic()<grace:
            if all(p.poll() is not None for p in self.roots.values()):break
            time.sleep(.02)
        signal_owned(signal.SIGKILL)
        for p in self.roots.values():
            try:p.wait(timeout=max(.001,self.origin+LIMITS['cleanup_offset_seconds']-time.monotonic()))
            except Exception as exc:errors.append(type(exc).__name__+':'+str(exc))
        # Only reap registered indirect children; never steal direct Popen statuses.
        for pid in set(self.owned)-set(self.roots):
            try:os.waitpid(pid,os.WNOHANG)
            except ChildProcessError:pass
            except OSError as exc:
                if exc.errno!=errno.ESRCH:errors.append(str(exc))
        live=[]
        for gid in self.groups:
            try:
                for n in self.group_members(gid):
                    if n.pid not in self.owned or n.create_time()!=self.owned[n.pid]:errors.append('UNREGISTERED_OR_REUSED_GROUP_MEMBER')
                    if n.status()!=self.ps.STATUS_ZOMBIE:live.append(n.pid)
            except Exception as exc:errors.append(str(exc))
        return {'cleanup_complete':not live and not errors,'live_members':live,'errors':errors}
    def child(self,argv,*,fds=(),input_bytes=b'',wall_cap=2.,overrides=None,limits_callback=None,tick=None,start_on_ready=False):
        self.check();waited_start=resource.getrusage(resource.RUSAGE_CHILDREN);start=time.monotonic();p=None;sel=selectors.DefaultSelector();stdout=bytearray();stderr=bytearray();sent=0;reason=None;stop_reasons=[];samples=[]
        def caps():
            os.umask(0o077);resource.setrlimit(resource.RLIMIT_CORE,(0,0));resource.setrlimit(resource.RLIMIT_FSIZE,(1048576,1048576));remaining=int(LIMITS['active_cpu_seconds']-self.cpu_high)
            if remaining<1:os._exit(125)
            resource.setrlimit(resource.RLIMIT_CPU,(min(remaining,1 if wall_cap<=2 else remaining),)*2)
        try:
            p=subprocess.Popen(argv,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,pass_fds=fds,start_new_session=True,env={'PATH':'/nonexistent','PYTHONDONTWRITEBYTECODE':'1','PYTHONNOUSERSITE':'1'},preexec_fn=caps)
            self.register(p)
            for stream,name in ((p.stdout,'stdout'),(p.stderr,'stderr')):os.set_blocking(stream.fileno(),False);sel.register(stream,selectors.EVENT_READ,name)
            if input_bytes and not start_on_ready:os.set_blocking(p.stdin.fileno(),False);sel.register(p.stdin,selectors.EVENT_WRITE,'stdin')
            elif not input_bytes:p.stdin.close()
            while True:
                if tick:tick()
                s=self.sample();local=dict(overrides or {})
                if limits_callback:local.update(limits_callback(s,bytes(stdout)))
                if start_on_ready and sent==0 and b'"event":"ready"' in stdout and not p.stdin.closed:
                    try:sel.get_key(p.stdin)
                    except KeyError:
                        os.set_blocking(p.stdin.fileno(),False);sel.register(p.stdin,selectors.EVENT_WRITE,'stdin')
                stop_reasons=self.reasons(s,local)
                samples.append(s)
                if len(samples)>64:samples.pop(0)
                if stop_reasons or time.monotonic()-start>=wall_cap:reason=','.join(stop_reasons) or 'ACTOR_OR_WORKER_WALL_STOP';break
                for key,_ in sel.select(.02):
                    if key.data=='stdin':
                        n=os.write(key.fd,input_bytes[sent:sent+4096]);sent+=n
                        if sent==len(input_bytes):sel.unregister(key.fileobj);key.fileobj.close()
                    else:
                        raw=os.read(key.fd,65536)
                        if not raw:sel.unregister(key.fileobj);continue
                        target=stdout if key.data=='stdout' else stderr;target.extend(raw);self.buffers=len(stdout)+len(stderr)
                        if self.buffers>131072:raise Blocked('CHILD_CAPTURE_LIMIT')
                if p.poll() is not None and not sel.get_map():break
            if reason:
                cleanup=self.cleanup()
            else:cleanup=self.cleanup()  # Sequential roots: also prove no leftover group members.
        except Exception as exc:
            reason=type(exc).__name__+':'+str(exc);cleanup=self.cleanup()
        finally:
            sel.close()
            if p is not None:
                for s in (p.stdin,p.stdout,p.stderr):
                    if s and not s.closed:s.close()
            self.buffers=0
        waited_end=resource.getrusage(resource.RUSAGE_CHILDREN);waited_delta=(waited_end.ru_utime+waited_end.ru_stime)-(waited_start.ru_utime+waited_start.ru_stime)
        return {'waited_child_CPU_seconds':waited_delta,'exit_code':None if p is None else p.returncode,'failure':reason,'stop_reasons':stop_reasons,'stdout':stdout.decode('ascii','backslashreplace'),'stderr':stderr.decode('utf-8','replace'),'elapsed_seconds':time.monotonic()-start,'samples':samples,'cleanup':cleanup}
