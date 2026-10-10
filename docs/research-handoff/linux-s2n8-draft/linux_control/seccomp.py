"""Linux x86_64 deny overlay; readonly namespace is the filesystem boundary."""
import ctypes,errno,os,platform,struct,sys
from model import Blocked
LD=0x20;JEQ=0x15;JSET=0x45;RET=0x06
ALLOW=0x7fff0000;KILL=0x80000000;DENY=0x00050000|errno.EPERM
# x86_64 native syscall ABI only; x32 and every other architecture killed.
BASE_DENY={41,42,43,44,45,46,47,48,49,50,51,52,53,54,55,56,57,58,101,155,161,165,166,272,288,299,303,304,307,308,310,311,319,321,322,323,425,426,427,435,437}
# Close alternate filesystem mutation routes, including native creat.
BASE_DENY.update({76,77,82,83,84,85,86,87,88,90,91,92,93,94,132,133,188,189,190,197,198,199,258,259,260,261,263,264,265,266,268,280,306,316})
WRITE_FLAGS=0o1|0o2|0o100|0o1000|0o2000|0o20200000

def instructions(final=False):
    if sys.platform!='linux' or platform.machine()!='x86_64':raise Blocked('SECCOMP_ARCH_UNSUPPORTED')
    code=[(LD,0,0,4),(JEQ,1,0,0xc000003e),(RET,0,0,KILL),(LD,0,0,0),(JSET,0,1,0x40000000),(RET,0,0,KILL)]
    for nr in sorted(BASE_DENY|({59} if final else set())):
        code.extend([(JEQ,0,1,nr),(RET,0,0,DENY)])
    for nr,argoffset in ((2,24),(257,32)):  # open.flags args[1]; openat.flags args[2]
        code.extend([(JEQ,0,4,nr),(LD,0,0,argoffset),(JSET,0,1,WRITE_FLAGS),(RET,0,0,DENY),(LD,0,0,0)])
    code.append((RET,0,0,ALLOW));return code

def bytes_filter(final=False):
    return b''.join(struct.pack('HBBI',*i) for i in instructions(final))

def sealed_fd(raw):
    import fcntl
    fd=os.memfd_create('pcg-public-bootstrap',os.MFD_CLOEXEC|os.MFD_ALLOW_SEALING)
    os.write(fd,raw);os.lseek(fd,0,os.SEEK_SET)
    fcntl.fcntl(fd,fcntl.F_ADD_SEALS,fcntl.F_SEAL_WRITE|fcntl.F_SEAL_GROW|fcntl.F_SEAL_SHRINK|fcntl.F_SEAL_SEAL)
    return fd

def install_final():
    class Filter(ctypes.Structure):_fields_=[('code',ctypes.c_ushort),('jt',ctypes.c_ubyte),('jf',ctypes.c_ubyte),('k',ctypes.c_uint)]
    class Program(ctypes.Structure):_fields_=[('len',ctypes.c_ushort),('filter',ctypes.POINTER(Filter))]
    rows=instructions(True);arr=(Filter*len(rows))(*(Filter(*x) for x in rows));prog=Program(len(rows),arr);libc=ctypes.CDLL(None,use_errno=True)
    if libc.prctl(38,1,0,0,0)!=0 or libc.prctl(22,2,ctypes.byref(prog),0,0)!=0:raise Blocked('SECCOMP_INSTALL_FAILED')
