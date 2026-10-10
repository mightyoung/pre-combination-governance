# Independent static review and accepted blockers

The fresh reviewer inspected all new control modules, tests and both qualification schemas without importing or executing them. Four high-severity findings were reported: hard RSS absent; incomplete descendant cleanup ownership; no independent deadline watchdog; writable namespace routes.

Namespace defenses were revised: read-only root/dev/proc remounts, native creat and other mutation syscall denial, and the source-write actor now targets `/pkg/tools/worker.py`. These revisions are statically present but untested.

The other three findings remain unresolved implementation blockers. Both supported entries now unconditionally reject startup before runtime/approval/actor/worker handling. Slot 11 separately refuses qualification because an ordinary controller timeout does not prove watchdog behavior. Follow-up static review found no metadata/signature bypass of these source-level blocks. It explicitly noted that metadata reads preceding the block do not establish bounded startup.

A final-receipt reserve bug was repaired and runtime fingerprinting uses guarded, chunked reads. These fixes do not establish kernel resource control. Default trust key and exact Linux runtime lock remain absent. Tests/actors/workers NOT RUN; no Linux qualification, observed timing or scientific success is asserted.
