"""Signed one-time platform approval and per-run capability chain; no keys bundled."""
import base64,os,time
from pathlib import Path
from model import Blocked,LIMITS,RUN_ID,canonical,digest,loads,signed_body

def verify_signature(doc,public_key):
    body=signed_body(doc)
    if not isinstance(public_key,str) or len(public_key)!=64:raise Blocked('TRUST_ROOT_UNPROVISIONED')
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    try:Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key)).verify(base64.b64decode(doc['signature'],validate=True),canonical(body))
    except Exception as exc:raise Blocked('SIGNATURE_INVALID') from exc
    return body

def verify_approval(envelope,policy,bindings):
    if policy.get('status')!='REVIEWED_TRUST_ROOT' or policy.get('execution_authorized') is not False:raise Blocked('TRUST_POLICY_UNPROVISIONED')
    b=verify_signature(envelope,policy.get('approval_public_key'))
    if b.get('authorization_status')!='EXPLICIT_LINUX_SINGLE_RUN_APPROVED' or b.get('schema_version')!='pcg-linux-approval.v1':raise Blocked('UNSIGNED_STATIC_PERMIT_NOT_APPROVAL')
    expected={'bindings':bindings,'limits':LIMITS,'methods':['ES-Rebuild','Proposed-current-stream'],'cell':'S2-N8','phase':'instrumented_warmup','maximum_attempts':1,'retries':0}
    for k,v in expected.items():
        if canonical(b.get(k))!=canonical(v):raise Blocked('APPROVAL_SCOPE_MISMATCH_'+k)
    if not RUN_ID.fullmatch(b.get('run_id','')):raise Blocked('INVALID_RUN_ID')
    if not isinstance(b.get('session_public_key'),str) or len(b['session_public_key'])!=64:raise Blocked('SESSION_KEY_MISSING')
    now=time.time()
    if type(b.get('not_before_utc')) not in (int,float) or type(b.get('expires_utc')) not in (int,float) or not b['not_before_utc']<=now<b['expires_utc'] or b['expires_utc']-b['not_before_utc']>3600:raise Blocked('APPROVAL_EXPIRED_OR_OVERBROAD')
    return b

def consume(approval,output_root):
    root=Path(output_root).resolve()
    if approval.get('output_root_sha256')!=digest(str(root).encode('utf-8')):raise Blocked('OUTPUT_ROOT_BINDING_MISMATCH')
    marker=root/('.consumed-'+approval['run_id'])
    # Existing writable output root is part of signed approval; no new permissions.
    fd=os.open(marker,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as f:f.write(canonical({'run_id':approval['run_id'],'status':'CONSUMED_ATTEMPT_NOT_RETRYABLE'}))
    out=root/approval['run_id']
    out.mkdir(mode=0o700)  # Existing output means stop, never overwrite or resume.
    return out

def session_signer(fd,approval):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
    raw=os.read(fd,33);os.close(fd)
    if len(raw)!=32:raise Blocked('SESSION_KEY_FD_MUST_BE_32_BYTES')
    key=Ed25519PrivateKey.from_private_bytes(raw)
    if key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw).hex()!=approval['session_public_key']:raise Blocked('SESSION_KEY_NOT_APPROVED')
    def sign(payload):return {'payload':payload,'signature':base64.b64encode(key.sign(canonical(payload))).decode('ascii')}
    return sign

def verify_capability(doc,approval,bindings,kind):
    b=verify_signature(doc,approval['session_public_key'])
    if b.get('kind')!=kind or b.get('run_id')!=approval['run_id'] or b.get('bindings')!=bindings:raise Blocked('CAPABILITY_BINDING_MISMATCH')
    if type(b.get('origin_monotonic')) not in (int,float) or type(b.get('deadline_monotonic')) not in (int,float) or not b['origin_monotonic']<=time.monotonic()<b['deadline_monotonic']<=b['origin_monotonic']+120:raise Blocked('CAPABILITY_EXPIRED')
    return b

REQUIRED={'read_positive','outside_read_denied','source_write_denied','outside_write_denied','symlink_escape_denied','loopback_live_positive','loopback_denied','fork_positive','fork_denied','term_resistant_child_cleanup','watchdog_group_cleanup','cpu_positive','cpu_aggregation','cpu_stop','single_rss_stop','aggregate_rss_stop','output_limit','global_deadline'}

def verify_qualification(q,approval,bindings,receipts):
    b=verify_capability(q,approval,bindings,'qualification')
    if b.get('status')!='PASSED' or len(b.get('probe_receipts',[]))!=16 or len(receipts)!=16:raise Blocked('COMPLETE_16_QUALIFICATION_REQUIRED')
    if [r.get('slot') for r in b['probe_receipts']]!=list(range(1,17)):raise Blocked('DUPLICATE_OR_MISSING_SLOT')
    from probes import SLOTS
    covered=set()
    for item,doc in zip(b['probe_receipts'],receipts):
        if digest(canonical(doc))!=item['sha256']:raise Blocked('PROBE_RECEIPT_HASH_MISMATCH')
        r=verify_capability(doc,approval,bindings,'probe_receipt')
        if r.get('slot')!=item['slot'] or r.get('status')!='PASSED' or r.get('covered_checks')!=item['covered_checks'] or r.get('cleanup_complete') is not True or r.get('covered_checks')!=SLOTS[item['slot']-1]['checks'] or r.get('origin_monotonic')!=b.get('origin_monotonic'):raise Blocked('PROBE_RECEIPT_NOT_ACTUALLY_QUALIFIED')
        covered.update(r['covered_checks'])
    if covered!=REQUIRED or set(b.get('covered_checks',[]))!=REQUIRED:raise Blocked('REQUIRED_CHECK_SET_MISMATCH')
    return b
