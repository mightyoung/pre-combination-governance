"""Future mocked supervision tests; WRITTEN NOT RUN. No process/namespace calls."""
import sys,unittest
from pathlib import Path
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from model import Blocked
from isolation import command
from budget import Ledger

class LinuxSupervisionDesign(unittest.TestCase):
    def test_argv_no_writable_host_bind_or_sidecar(self):
        spec={'namespace_flags':['--unshare-all','--die-with-parent','--new-session','--cap-drop','ALL','--clearenv'],'readonly_mounts':[{'source':'/reviewed/code','target':'/control'}],'symlinks':[]}
        argv=command(spec,{'bwrap':'/reviewed/bwrap','python':'/reviewed/python'},7,8)
        self.assertEqual(argv.count('--remount-ro'),3);self.assertIn('--seccomp',argv);self.assertIn('--ro-bind',argv);self.assertNotIn('--bind',argv)
        self.assertIn('-S',argv);self.assertNotIn('/home',argv);self.assertNotIn('sidecar',str(argv))
    def test_owned_AccessDenied_is_not_ignored(self):
        # Test intent: a fake psutil backend raises owned-tree AccessDenied; expect Blocked.
        l=object.__new__(Ledger);ps=Mock();ps.NoSuchProcess=type('Missing',(Exception,),{});ps.AccessDenied=type('Denied',(Exception,),{});l.ps=ps;l.roots={1:Mock()};l.owned={1:1.0}
        with patch.object(l,'_node',side_effect=ps.AccessDenied()):
            with self.assertRaisesRegex(Blocked,'OWNED_TREE_ACCESS_DENIED'):l.sample()
    def test_PID_reuse_is_blocked(self):
        l=object.__new__(Ledger);l.ps=Mock();l.owned={1:10.0};l.ps.Process.return_value.create_time.return_value=11.0
        with self.assertRaisesRegex(Blocked,'OWNED_PID_REUSED'):l._node(1)
    def test_group_permission_failure_is_unknown(self):
        l=object.__new__(Ledger);ps=Mock();ps.NoSuchProcess=type('Missing',(Exception,),{});ps.AccessDenied=type('Denied',(Exception,),{});ps.pids.return_value=[12];l.ps=ps
        with patch('budget.os.getpgid',side_effect=PermissionError()):
            with self.assertRaisesRegex(Blocked,'GROUP_ENUMERATION_UNCERTAIN'):l.group_members(12)
    def test_filter_rejects_wrong_architecture(self):
        import seccomp
        with patch('seccomp.sys.platform','darwin'):
            with self.assertRaisesRegex(Blocked,'SECCOMP_ARCH_UNSUPPORTED'):seccomp.instructions()
    def test_x32_and_exec_denied_in_final_policy(self):
        import seccomp
        with patch('seccomp.sys.platform','linux'),patch('seccomp.platform.machine',return_value='x86_64'):
            code=seccomp.instructions(True)
        self.assertIn((seccomp.JSET,0,1,0x40000000),code);self.assertIn((seccomp.JEQ,0,1,59),code)
    def test_open_write_flags_inspected(self):
        import seccomp
        with patch('seccomp.sys.platform','linux'),patch('seccomp.platform.machine',return_value='x86_64'):
            code=seccomp.instructions(True)
        self.assertIn((seccomp.LD,0,0,24),code);self.assertIn((seccomp.LD,0,0,32),code)
        self.assertIn((seccomp.JSET,0,1,seccomp.WRITE_FLAGS),code)

    def test_hard_containment_cannot_be_enabled_by_metadata(self):
        from readiness import require_hard_containment
        with self.assertRaisesRegex(Blocked,'UNIMPLEMENTED_HARD_CONTAINMENT_BOUNDARY'):
            require_hard_containment()
    def test_native_creat_and_mutation_syscalls_denied(self):
        import seccomp
        self.assertTrue({76,77,82,83,84,85,87,258,263,264,316}.issubset(seccomp.BASE_DENY))

if __name__=='__main__':unittest.main()
