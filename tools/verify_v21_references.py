from __future__ import annotations

import concurrent.futures
import json
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
MAIN = ROOT / "00-论文-中文阅读稿v21-生命周期一致组合前治理与IF创新主线版.md"
OUT = ROOT / "v21-参考文献外部元数据核验.json"
UA = "v21-reference-integrity-check/1.0 (academic manuscript verification)"

OFFICIAL_MARKERS = {
    1: ["IEC 61511-1", "Functional safety"],
    2: ["IEC 61508-6", "Functional safety"],
    8: ["IEC 61882", "Hazard and operability"],
    28: ["PROV-O", "PROV Ontology"],
    36: ["Encoding information lineage", "distributed fusion"],
    39: ["On distinct belief functions", "Dempster-Shafer"],
    47: ["Fault Tree Handbook", "NUREG-0492"],
}


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def title_coverage(title: str, reference: str) -> float:
    stop = {"the", "a", "an", "of", "and", "for", "in", "on", "to", "with", "based", "using"}
    tokens = [x for x in normalize(title).split() if len(x) > 2 and x not in stop]
    ref_tokens = set(normalize(reference).split())
    return 1.0 if not tokens else sum(t in ref_tokens for t in tokens) / len(tokens)


def get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_text(url: str) -> tuple[int, str, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read(2_000_000).decode("utf-8", errors="replace")
        return resp.status, resp.geturl(), body


def verify_one(item: tuple[int, str]) -> dict:
    number, reference = item
    doi_match = re.search(r"https?://doi\.org/([^\s.]+(?:\.[^\s.]+)*)", reference, re.I)
    if doi_match:
        doi = doi_match.group(1).rstrip(".")
        url = "https://api.crossref.org/works/" + urllib.parse.quote(doi, safe="")
        try:
            payload = get_json(url)["message"]
            title = " ".join(payload.get("title") or [])
            coverage = title_coverage(title, reference)
            return {
                "reference": number,
                "kind": "doi_crossref",
                "identifier": doi,
                "url": url,
                "returned_title": title,
                "title_token_coverage": round(coverage, 4),
                "status": "PASS" if coverage >= 0.70 else "FAIL_TITLE_MISMATCH",
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "reference": number,
                "kind": "doi_crossref",
                "identifier": doi,
                "url": url,
                "status": "FAIL_RETRIEVAL",
                "error": f"{type(exc).__name__}: {exc}",
            }

    url_match = re.search(r"https?://\S+", reference)
    if not url_match:
        return {"reference": number, "kind": "none", "status": "FAIL_NO_IDENTIFIER"}
    url = url_match.group(0).rstrip(".")
    try:
        code, final_url, body = get_text(url)
        normalized = normalize(body)
        markers = OFFICIAL_MARKERS.get(number, [])
        marker_results = {m: normalize(m) in normalized for m in markers}
        ok = code == 200 and (not markers or all(marker_results.values()))
        return {
            "reference": number,
            "kind": "official_url",
            "identifier": url,
            "url": url,
            "final_url": final_url,
            "http_status": code,
            "marker_results": marker_results,
            "status": "PASS" if ok else "FAIL_URL_OR_MARKER",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "reference": number,
            "kind": "official_url",
            "identifier": url,
            "url": url,
            "status": "FAIL_RETRIEVAL",
            "error": f"{type(exc).__name__}: {exc}",
        }


def main() -> None:
    text = MAIN.read_text(encoding="utf-8")
    refs = [(int(n), body.strip()) for n, body in re.findall(r"(?m)^\[(\d+)\]\s+(.+)$", text)]
    if [n for n, _ in refs] != list(range(1, 51)):
        raise AssertionError("expected reference sequence 1..50")
    started = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(verify_one, refs))
    results.sort(key=lambda x: x["reference"])
    failures = [x for x in results if x["status"] != "PASS"]
    report = {
        "status": "PASS" if not failures else "FAIL",
        "reference_count": len(results),
        "passed": len(results) - len(failures),
        "failed": len(failures),
        "elapsed_seconds": round(time.time() - started, 3),
        "results": results,
        "failures": failures,
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ["status", "reference_count", "passed", "failed", "elapsed_seconds"]}, ensure_ascii=False, indent=2))
    if failures:
        for failure in failures:
            print(json.dumps(failure, ensure_ascii=False))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
