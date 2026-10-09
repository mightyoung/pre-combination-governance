#!/usr/bin/env python3
"""Collapse an accidental doubled v6.6.1 label in the generated DOCX body."""

from __future__ import annotations

import os
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
                if item.filename.endswith(".xml"):
                    data = data.replace(b"v6.6.1.1", b"v6.6.1")
                dst.writestr(item, data)
        os.replace(temp_path, OUT)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    print(OUT)


if __name__ == "__main__":
    main()
