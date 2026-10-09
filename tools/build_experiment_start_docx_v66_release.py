#!/usr/bin/env python3
"""Release wrapper that builds and normalizes the v6.6 DOCX settings."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "tools" / "build_experiment_start_docx_v66.py"
OUT = ROOT / "实验启动计划v6.6-双机执行与资源预算.docx"
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def run_base() -> None:
    spec = importlib.util.spec_from_file_location("v66_docx_base", BASE)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load DOCX builder")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.build()


def normalize_settings() -> None:
    with ZipFile(OUT, "r") as src:
        entries = [(item, src.read(item.filename)) for item in src.infolist()]
    normalized = []
    for item, data in entries:
        if item.filename == "word/settings.xml":
            root = ET.fromstring(data)
            zoom = root.find(f"{{{W}}}zoom")
            if zoom is None:
                zoom = ET.Element(f"{{{W}}}zoom")
                root.insert(0, zoom)
            zoom.set(f"{{{W}}}val", "bestFit")
            zoom.set(f"{{{W}}}percent", "100")
            data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        normalized.append((item, data))
    with NamedTemporaryFile(delete=False, suffix=".docx", dir=OUT.parent) as tmp:
        temp_path = Path(tmp.name)
    try:
        with ZipFile(temp_path, "w", ZIP_DEFLATED) as dst:
            for item, data in normalized:
                dst.writestr(item, data)
        os.replace(temp_path, OUT)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def main() -> None:
    run_base()
    normalize_settings()
    print(OUT)


if __name__ == "__main__":
    main()
