from __future__ import annotations

import json
import re
import time
import unicodedata
import urllib.error
import urllib.request

import verify_v21_references as base


def normalize(value: str) -> str:
    value = re.sub(r"[–—−‐‑]", " ", value)
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def get_json(url: str) -> dict:
    for attempt in range(6):
        request = urllib.request.Request(url, headers={"User-Agent": base.UA, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504} or attempt == 5:
                raise
            time.sleep(min(30, 2 ** attempt))
    raise AssertionError("unreachable")


def get_text(url: str) -> tuple[int, str, str]:
    for attempt in range(4):
        request = urllib.request.Request(url, headers={"User-Agent": base.UA})
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                body = response.read(2_000_000).decode("utf-8", errors="replace")
                return response.status, response.geturl(), body
        except (TimeoutError, urllib.error.URLError):
            if attempt == 3:
                raise
            time.sleep(min(15, 2 ** attempt))
    raise AssertionError("unreachable")


def main() -> None:
    base.normalize = normalize
    base.get_json = get_json
    base.get_text = get_text
    previous = json.loads(base.OUT.read_text(encoding="utf-8"))
    refs = {int(n): body.strip() for n, body in re.findall(r"(?m)^\[(\d+)\]\s+(.+)$", base.MAIN.read_text(encoding="utf-8"))}
    passed = {int(x["reference"]): x for x in previous["results"] if x["status"] == "PASS"}
    pending_numbers = [n for n in range(1, 51) if n not in passed]
    retried = []
    for n in pending_numbers:
        retried.append(base.verify_one((n, refs[n])))
        time.sleep(1.0)
    results = sorted([*passed.values(), *retried], key=lambda x: x["reference"])
    failures = [x for x in results if x["status"] != "PASS"]
    report = {
        "status": "PASS" if not failures else "FAIL",
        "reference_count": len(results),
        "passed": len(results) - len(failures),
        "failed": len(failures),
        "results": results,
        "failures": failures,
    }
    base.OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ["status", "reference_count", "passed", "failed"]}, ensure_ascii=False, indent=2))
    if failures:
        for item in failures:
            print(json.dumps(item, ensure_ascii=False))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
