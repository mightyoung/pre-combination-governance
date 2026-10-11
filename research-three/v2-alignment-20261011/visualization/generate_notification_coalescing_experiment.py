#!/usr/bin/env python3
"""Regenerate the synthetic reminder-action comparison JSON and HTML."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "risk-fusion-bench/src"))

from rfb.research.alert_action_experiment_scenarios import (  # noqa: E402
    build_comparison,
    render_html,
)


OUT = Path(__file__).resolve().parent


def main() -> None:
    result = build_comparison()
    result["source_revision"] = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    json_path = OUT / "notification-coalescing-experiment-data.json"
    html_path = OUT / "notification-coalescing-experiment.html"
    json_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    html_path.write_text(render_html(result), encoding="utf-8")
    print(f"Wrote {json_path.relative_to(ROOT)}")
    print(f"Wrote {html_path.relative_to(ROOT)}")
    print(f"Unique semantic actions: {result['input']['unique_action_count']}")
    for item in result["window_results"]:
        print(
            f"window={item['window_seconds']}s "
            f"per_association={item['per_association']['notification_action_count']} "
            f"card_coalesce={item['card_coalesce']['notification_action_count']} "
            f"revisions={item['card_coalesce']['semantic_card_revision_count']}"
        )


if __name__ == "__main__":
    main()
