from __future__ import annotations

import hashlib
import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path

import paramiko


HOST = "192.168.11.16"
PORT = 10022
USER = "r4900g3"
EXPECTED_HOST_KEY_SHA256 = "eDfwLjrpTces2mQp4d+gKdg2i/4t7k7sLfF/nLtx1oA"
REMOTE_ROOT = "/home/r4900g3/yhh/provenance-fusion/runs/shakedown/SHK-001A-resource-v611-20260715"
LOCAL_ROOT = Path("outputs/restore-cache/SHK-001A-resource-v611-20260715")
REPORT_PATH = Path("记录/SHK001A-v6.11-本机恢复校验.json")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def host_key_fingerprint(key: paramiko.PKey) -> str:
    raw = hashlib.sha256(key.asbytes()).digest()
    import base64

    return base64.b64encode(raw).decode("ascii").rstrip("=")


def walk_sftp(sftp: paramiko.SFTPClient, remote_dir: str):
    for entry in sorted(sftp.listdir_attr(remote_dir), key=lambda item: item.filename):
        remote_path = f"{remote_dir}/{entry.filename}"
        if stat.S_ISDIR(entry.st_mode):
            yield from walk_sftp(sftp, remote_path)
        elif stat.S_ISREG(entry.st_mode):
            yield remote_path, entry


def main() -> None:
    password = os.environ.get("YHH_SSH_PASSWORD")
    if not password:
        raise SystemExit("YHH_SSH_PASSWORD is required")

    transport = paramiko.Transport((HOST, PORT))
    transport.start_client(timeout=15)
    actual_fingerprint = host_key_fingerprint(transport.get_remote_server_key())
    if actual_fingerprint != EXPECTED_HOST_KEY_SHA256:
        transport.close()
        raise RuntimeError(
            f"host key mismatch: expected {EXPECTED_HOST_KEY_SHA256}, got {actual_fingerprint}"
        )
    transport.auth_password(USER, password)
    sftp = paramiko.SFTPClient.from_transport(transport)

    LOCAL_ROOT.mkdir(parents=True, exist_ok=True)
    files = []
    total_bytes = 0
    for remote_path, attrs in walk_sftp(sftp, REMOTE_ROOT):
        relative = Path(remote_path.removeprefix(REMOTE_ROOT).lstrip("/"))
        local_path = LOCAL_ROOT / relative
        local_path.parent.mkdir(parents=True, exist_ok=True)
        sftp.get(remote_path, str(local_path))
        digest = sha256_file(local_path)
        size = local_path.stat().st_size
        total_bytes += size
        files.append(
            {
                "relative_path": relative.as_posix(),
                "bytes": size,
                "remote_bytes": attrs.st_size,
                "sha256": digest,
                "size_match": size == attrs.st_size,
            }
        )

    sftp.close()
    transport.close()

    qa_path = LOCAL_ROOT / "qa-report.json"
    qa = json.loads(qa_path.read_text(encoding="utf-8")) if qa_path.exists() else None
    report = {
        "schema_version": "v6.11-shk001a-restore-1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "classification": "NON_CONFIRMATORY_RESTORE_CACHE_NOT_DURABLE_ARCHIVE",
        "source": {"host": f"{HOST}:{PORT}", "remote_root": REMOTE_ROOT},
        "destination": str(LOCAL_ROOT.resolve()),
        "host_key_sha256": actual_fingerprint,
        "file_count": len(files),
        "total_bytes": total_bytes,
        "all_sizes_match": all(item["size_match"] for item in files),
        "qa_report_present": qa is not None,
        "qa_status": (qa or {}).get("status"),
        "files": files,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("classification", "file_count", "total_bytes", "all_sizes_match", "qa_report_present", "qa_status")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
