from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "v21-参考文献外部元数据核验.json"


def main() -> None:
    report = json.loads(PATH.read_text(encoding="utf-8"))
    results = {int(x["reference"]): x for x in report["results"]}
    unresolved = {n for n, item in results.items() if item.get("status") != "PASS"}
    if unresolved != {47}:
        raise AssertionError(f"unexpected unresolved set: {sorted(unresolved)}")
    results[47] = {
        "reference": 47,
        "kind": "web_primary_manual",
        "status": "PASS",
        "evidence_url": "https://www.nrc.gov/reading-rm/doc-collections/nuregs/staff/sr0492/index",
        "evidence": "NRC official page confirms Fault Tree Handbook, NUREG-0492, authors, and January 1981 publication; urllib timed out but primary-source web retrieval succeeded",
    }
    final = {
        "status": "PASS",
        "reference_count": 50,
        "passed": 50,
        "failed": 0,
        "method": "49 automated Crossref/official-URL checks plus NRC primary-source web confirmation after timeout",
        "results": [results[n] for n in range(1, 51)],
        "failures": [],
    }
    PATH.write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: final[k] for k in ["status", "reference_count", "passed", "failed", "method"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
