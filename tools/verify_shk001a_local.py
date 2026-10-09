from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path("outputs/restore-cache/SHK-001A-resource-v611-20260715")
REPORT = Path("SHK001A-v6.11-本机恢复校验.json")


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


files = []
for path in sorted(item for item in ROOT.rglob("*") if item.is_file()):
    files.append(
        {
            "relative_path": path.relative_to(ROOT).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": digest(path),
        }
    )

hashes = {item["relative_path"]: item["sha256"] for item in files}
manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
qa = json.loads((ROOT / "qa.json").read_text(encoding="utf-8"))
checks = [
    hashes.get(item["file"]) == item["sha256"]
    and (ROOT / item["file"]).stat().st_size == item["bytes"]
    for item in manifest["artifacts"]
]

report = {
    "schema_version": "v6.11-shk001a-restore-2",
    "created_at_utc": datetime.now(timezone.utc).isoformat(),
    "classification": "NON_CONFIRMATORY_RESTORE_CACHE_NOT_DURABLE_ARCHIVE",
    "source": {
        "host": "192.168.11.16:10022",
        "remote_root": "/home/r4900g3/yhh/provenance-fusion/runs/shakedown/SHK-001A-resource-v611-20260715",
    },
    "destination": ROOT.as_posix(),
    "host_key_sha256": "eDfwLjrpTces2mQp4d+gKdg2i/4t7k7sLfF/nLtx1oA",
    "file_count": len(files),
    "total_bytes": sum(item["bytes"] for item in files),
    "qa_report_present": True,
    "qa_status": qa.get("status"),
    "confirmatory": qa.get("confirmatory"),
    "claim_support": qa.get("claim_support"),
    "non_confirmatory_marker_present": (ROOT / "NON_CONFIRMATORY_DO_NOT_PROMOTE").exists(),
    "manifest_artifact_count": len(checks),
    "all_manifest_hashes_match": bool(checks) and all(checks),
    "all_qa_checks_pass": all(qa.get("checks", {}).values()),
    "files": files,
}
REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({key: report[key] for key in ("file_count", "total_bytes", "qa_status", "confirmatory", "all_manifest_hashes_match", "all_qa_checks_pass")}, ensure_ascii=False))
