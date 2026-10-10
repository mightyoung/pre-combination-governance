"""Interfaces for an existing approved Linux backend, not a fake implementation.

No backend is provisioned or claimed here. The required external guardian must
start before exec of Python, cover bootstrap/inventory/startup, and own stable
kernel membership. No user-supplied mapping, psutil scan or signed permit can
construct that backend. Wiring one requires a new reviewed source change and
read-only target-environment capability evidence; this module changes no OS state.
"""
from abc import abstractmethod
from typing import Mapping,Protocol,NoReturn
from model import Blocked

class ApprovedContainmentBackend(Protocol):
    scope_id:str
    approved_guard_public_key:str
    previous_actor_identity:Mapping[str,int]
    @abstractmethod
    def launch_under_existing_guard(self,*,argv:tuple[str,...],bindings:Mapping[str,str],limits:Mapping[str,int])->Mapping[str,object]:
        """External service: guard and kernel ownership precede exec; no bare Popen."""
        raise NotImplementedError('NO_APPROVED_BACKEND_IMPLEMENTATION')
    @abstractmethod
    def verify_preexec_guard(self,*,origin_ns:int,deadline_ns:int,bindings:Mapping[str,str])->None:
        """Verify externally authenticated ready receipt; guardian predates exec."""
        raise NotImplementedError('NO_APPROVED_BACKEND_IMPLEMENTATION')
    @abstractmethod
    def authenticated_reaped_cpu_receipt(self,*,fixture_nonce:str,reaped_slot:int,current_slot:int)->dict:
        """Return guardian-signed envelope; key must derive from approved preexec grant."""
        raise NotImplementedError('NO_APPROVED_BACKEND_IMPLEMENTATION')
    @abstractmethod
    def assert_kernel_limits_and_membership(self)->None:
        """Unknown/absent hard memory/aggregate CPU or stable ownership must raise."""
        raise NotImplementedError('NO_APPROVED_BACKEND_IMPLEMENTATION')
    @abstractmethod
    def terminate_scope_and_prove_empty(self,*,deadline_ns:int)->Mapping[str,object]:
        """Kernel-owned descendants across reparent/reap; unknown cleanup raises."""
        raise NotImplementedError('NO_APPROVED_BACKEND_IMPLEMENTATION')

def require_approved_backend(*,approved_run_id:str|None=None,approved_bindings:Mapping[str,str]|None=None)->NoReturn:
    raise Blocked('APPROVED_EXISTING_LINUX_BACKEND_NOT_DELEGATED')
