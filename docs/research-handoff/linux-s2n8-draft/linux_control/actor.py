"""Synthetic bounded actors; no scientific imports. Not run in this review."""
import ctypes,json,os,signal,socket,time,sys
from model import canonical

def emit(v):
    os.write(1,canonical(v)+b'\n')

def run(config):
    libc=ctypes.CDLL(None,use_errno=True)
    if libc.prctl(1,signal.SIGKILL,0,0,0)!=0:raise RuntimeError('ACTOR_PDEATHSIG_FAILED')
    mode=config['mode'];nonce=config['nonce'];emit({'event':'ready','nonce':nonce})
    if sys.stdin.buffer.readline(4)!=b'go\n':raise RuntimeError('CONTROLLER_READY_HANDSHAKE_MISSING')
    try:
        if mode in ('read','symlink'):
            with open(config['path'],'rb') as f:raw=f.read(129)
            emit({'event':'result','nonce':nonce,'value':raw.decode('ascii')})
        elif mode=='write':
            with open(config['path'],'wb') as f:f.write(b'forbidden')
            emit({'event':'unexpected_write','nonce':nonce})
        elif mode=='loopback':
            with socket.socket() as s:
                s.settimeout(1);s.connect(('127.0.0.1',config['port']));s.sendall(nonce.encode()+b'\n');value=s.recv(128)
            emit({'event':'result','nonce':nonce,'value':value.decode('ascii')})
        elif mode=='fork':
            child=os.fork()
            if child==0:os._exit(0)
            pid,status=os.waitpid(child,0);emit({'event':'fork_result','nonce':nonce,'children':1,'wait_status':status})
        elif mode=='term':
            signal.signal(signal.SIGTERM,signal.SIG_IGN);child=os.fork()
            if child==0:
                libc.prctl(1,signal.SIGKILL,0,0,0);deadline=time.monotonic()+2
                while time.monotonic()<deadline:time.sleep(.01)
                os._exit(0)
            emit({'event':'child_ready','nonce':nonce,'child_pid':child,'children':1})
            deadline=time.monotonic()+2
            while time.monotonic()<deadline:time.sleep(.01)
            os.waitpid(child,0)
        elif mode=='cpu':
            start=time.process_time()
            while time.process_time()-start<config['CPU_target']:pass
            emit({'event':'cpu_done','nonce':nonce})
        elif mode=='rss':
            block=bytearray(12*1024*1024)
            for i in range(0,len(block),4096):block[i]=1
            emit({'event':'allocated','nonce':nonce,'bytes':len(block)});time.sleep(1)
        elif mode=='output':
            for _ in range(1024):os.write(1,b'x'*1024)
        elif mode=='deadline':time.sleep(1)
        else:raise RuntimeError('UNKNOWN_ACTOR_MODE')
        return 0
    except OSError as exc:
        emit({'event':'denied','nonce':nonce,'errno':exc.errno});return 77
