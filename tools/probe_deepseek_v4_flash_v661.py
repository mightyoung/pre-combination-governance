#!/usr/bin/env python3
"""Sanitized DeepSeek V4 Flash experiment probe.

Dry-run is the default.  A real request requires both --execute and the
DEEPSEEK_API_KEY environment variable.  The script never writes the key.
It is a connectivity/contract probe, not the final acquisition runner.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


MODEL = "deepseek-v4-flash"
BASE_URL = "https://api.deepseek.com"


def canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_request(observation: dict) -> dict:
    system_prompt = (
        "You are a frozen operational-evidence mapper. Output json only. "
        "Never infer hidden truth, future state, severity labels, correct actions, "
        "or evaluation endpoints. Return {\"claims\":[],\"mapping_status\":\"ok|unknown\"}."
    )
    return {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "Map this operational observation to json:\n" + canonical_json(observation)},
        ],
        "temperature": 0,
        "top_p": 1,
        "stream": False,
        "max_tokens": 2048,
        "response_format": {"type": "json_object"},
        "tools": [],
        "thinking": {"type": "disabled"},
    }


def sanitize_headers(headers) -> dict:
    keep = {"date", "content-type", "x-request-id", "request-id", "cf-ray", "server"}
    return {k.lower(): v for k, v in headers.items() if k.lower() in keep}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="send one real API request")
    parser.add_argument("--observation-json", type=Path, help="small shakedown operational observation JSON")
    parser.add_argument("--output", type=Path, help="write sanitized response ledger JSON")
    args = parser.parse_args()

    observation = {"sensor_status": "shakedown", "value": 0.0, "unit": "normalized"}
    if args.observation_json:
        observation = json.loads(args.observation_json.read_text(encoding="utf-8"))
    request_body = build_request(observation)
    canonical = canonical_json(request_body)
    result = {
        "probe_version": "v6.6.1",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "execute": bool(args.execute),
        "base_url": BASE_URL,
        "model": MODEL,
        "api_key_present": bool(os.environ.get("DEEPSEEK_API_KEY")),
        "canonical_request_sha256": sha256_text(canonical),
        "request_without_secret": request_body,
    }
    if not args.execute:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("DEEPSEEK_API_KEY is required with --execute", file=sys.stderr)
        return 2
    req = urllib.request.Request(
        BASE_URL + "/chat/completions",
        data=canonical.encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=180) as response:
            raw = response.read().decode("utf-8")
            result.update({
                "http_status": response.status,
                "response_headers": sanitize_headers(response.headers),
                "latency_ms": round((time.perf_counter() - start) * 1000, 3),
                "raw_response": json.loads(raw),
            })
    except urllib.error.HTTPError as exc:
        result.update({
            "http_status": exc.code,
            "response_headers": sanitize_headers(exc.headers),
            "latency_ms": round((time.perf_counter() - start) * 1000, 3),
            "error_body": exc.read().decode("utf-8", errors="replace"),
        })
    except Exception as exc:
        result.update({
            "http_status": None,
            "latency_ms": round((time.perf_counter() - start) * 1000, 3),
            "transport_error_type": type(exc).__name__,
            "transport_error": str(exc),
        })
    output_text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(output_text, encoding="utf-8")
    print(output_text, end="")
    return 0 if result.get("http_status") == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
