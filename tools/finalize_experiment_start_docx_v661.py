#!/usr/bin/env python3
"""Normalize the v6.6.1 DOCX zoom attribute without namespace loss."""

from __future__ import annotations

import os
import re
from pathlib import Path
from tempfile import NamedTemporaryFile
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "实验启动计划v6.6.1-DeepSeek在线API与双机资源预算.docx"


def main() -> None:
    with ZipFile(OUT, "r") as src:
        entries = [(item, src.read(item.filename)) for item in src.infolist()]
    with NamedTemporaryFile(delete=False, suffix=".docx", dir=OUT.parent) as tmp:
        temp_path = Path(tmp.name)
    try:
        with ZipFile(temp_path, "w", ZIP_DEFLATED) as dst:
            for item, data in entries:
                if item.filename == "word/settings.xml":
                    match = re.search(br"<w:zoom\b[^>]*/>", data)
                    if match and b"w:percent=" not in match.group(0):
                        replacement = match.group(0)[:-2] + b' w:percent="100"/>'
                        data = data[:match.start()] + replacement + data[match.end():]
                dst.writestr(item, data)
        os.replace(temp_path, OUT)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    print(OUT)


if __name__ == "__main__":
    main()
