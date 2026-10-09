#!/usr/bin/env python3
"""Add the official V4 Preview/no-snapshot limitation to the v6.6.1 plan."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "实验启动计划v6.6.1-DeepSeek在线API与双机资源预算.md"


def main() -> None:
    text = PATH.read_text(encoding="utf-8")
    note = (
        "DeepSeek 官方 2026-04-24 公告将 V4 标为 Preview，公开 API 未提供日期固定的 snapshot ID，"
        "也未公开可请求的随机 seed。因此它必须被视为会漂移的托管服务，而不是可完全重生成的本地模型。"
    )
    marker = "DeepSeek 只允许作为**公共、冻结的外部随机 SourceAdapter**"
    if note not in text:
        if marker not in text:
            raise RuntimeError("API contract marker not found")
        text = text.replace(marker, note + "\n\n" + marker, 1)
    source = "15. DeepSeek. DeepSeek V4 Preview Release. https://api-docs.deepseek.com/news/news260424/"
    if source not in text:
        anchor = "14. DeepSeek. Change Log. https://api-docs.deepseek.com/updates/"
        if anchor not in text:
            raise RuntimeError("Source anchor not found")
        text = text.replace(anchor, anchor + "\n" + source, 1)
    PATH.write_text(text, encoding="utf-8")
    print(PATH)


if __name__ == "__main__":
    main()
