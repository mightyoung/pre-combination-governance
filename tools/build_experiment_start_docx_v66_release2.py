#!/usr/bin/env python3
"""Schema-normalized release builder for the v6.6 DOCX."""

from __future__ import annotations

import importlib.util
import os
import re
from pathlib import Path
from tempfile import NamedTemporaryFile
from zipfile import ZIP_DEFLATED, ZipFile

from docx.oxml import OxmlElement
from docx.oxml.ns import qn


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "tools" / "build_experiment_start_docx_v66.py"
OUT = ROOT / "实验启动计划v6.6-双机执行与资源预算.docx"


def load_base():
    spec = importlib.util.spec_from_file_location("v66_docx_base", BASE)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load DOCX builder")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def install_cell_margin_fix(module) -> None:
    def set_cell_margins(cell, top=80, start=100, bottom=80, end=100):
        tc_pr = cell._tc.get_or_add_tcPr()
        tc_mar = tc_pr.find(qn("w:tcMar"))
        if tc_mar is None:
            tc_mar = OxmlElement("w:tcMar")
            later_tags = {qn("w:textDirection"), qn("w:tcFitText"), qn("w:vAlign"), qn("w:hideMark")}
            insert_at = len(tc_pr)
            for index, child in enumerate(tc_pr):
                if child.tag in later_tags:
                    insert_at = index
                    break
            tc_pr.insert(insert_at, tc_mar)
        for margin, value in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
            node = tc_mar.find(qn(f"w:{margin}"))
            if node is None:
                node = OxmlElement(f"w:{margin}")
                tc_mar.append(node)
            node.set(qn("w:w"), str(value))
            node.set(qn("w:type"), "dxa")

    module.set_cell_margins = set_cell_margins


def patch_zoom_without_namespace_loss() -> None:
    with ZipFile(OUT, "r") as src:
        entries = [(item, src.read(item.filename)) for item in src.infolist()]
    patched = []
    for item, data in entries:
        if item.filename == "word/settings.xml":
            if b"<w:zoom" in data and b"w:percent=" not in re.search(br"<w:zoom[^>]*/>", data).group(0):
                data = re.sub(br"(<w:zoom\b[^>]*?)(/>)", br'\1 w:percent="100"\2', data, count=1)
        patched.append((item, data))
    with NamedTemporaryFile(delete=False, suffix=".docx", dir=OUT.parent) as tmp:
        temp_path = Path(tmp.name)
    try:
        with ZipFile(temp_path, "w", ZIP_DEFLATED) as dst:
            for item, data in patched:
                dst.writestr(item, data)
        os.replace(temp_path, OUT)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def main() -> None:
    module = load_base()
    install_cell_margin_fix(module)
    module.build()
    patch_zoom_without_namespace_loss()
    print(OUT)


if __name__ == "__main__":
    main()
