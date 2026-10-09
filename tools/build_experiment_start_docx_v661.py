#!/usr/bin/env python3
"""Build the v6.6.1 DeepSeek-aware DOCX sibling using the verified v6.6 builder."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from zipfile import ZIP_DEFLATED, ZipFile

from docx.oxml import OxmlElement
from docx.oxml.ns import qn


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "tools" / "build_experiment_start_docx_v66.py"
OUT = ROOT / "实验启动计划v6.6.1-DeepSeek在线API与双机资源预算.docx"
SRC = ROOT / "实验启动计划v6.6.1-DeepSeek在线API与双机资源预算.md"


def load_base():
    spec = importlib.util.spec_from_file_location("v661_docx_base", BASE)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load v6.6 DOCX builder")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def install_ooxml_fixes(module) -> None:
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

    def set_cell_shading(cell, fill):
        tc_pr = cell._tc.get_or_add_tcPr()
        shd = tc_pr.find(qn("w:shd"))
        if shd is None:
            shd = OxmlElement("w:shd")
            later_tags = {
                qn("w:noWrap"), qn("w:tcMar"), qn("w:textDirection"),
                qn("w:tcFitText"), qn("w:vAlign"), qn("w:hideMark"),
            }
            insert_at = len(tc_pr)
            for index, child in enumerate(tc_pr):
                if child.tag in later_tags:
                    insert_at = index
                    break
            tc_pr.insert(insert_at, shd)
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:fill"), fill)

    module.set_cell_margins = set_cell_margins
    module.set_cell_shading = set_cell_shading


def patch_package() -> None:
    with ZipFile(OUT, "r") as src:
        entries = [(item, src.read(item.filename)) for item in src.infolist()]
    with NamedTemporaryFile(delete=False, suffix=".docx", dir=OUT.parent) as tmp:
        temp_path = Path(tmp.name)
    try:
        with ZipFile(temp_path, "w", ZIP_DEFLATED) as dst:
            for item, data in entries:
                if item.filename.endswith(".xml"):
                    data = data.replace(b"v6.6", b"v6.6.1")
                    if item.filename == "word/settings.xml" and b"w:percent=" not in data:
                        data = data.replace(b"<w:zoom/>", b'<w:zoom w:percent="100"/>', 1)
                dst.writestr(item, data)
        os.replace(temp_path, OUT)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def main() -> None:
    module = load_base()
    module.SRC = SRC
    module.OUT = OUT
    install_ooxml_fixes(module)
    module.build()
    patch_package()
    print(OUT)


if __name__ == "__main__":
    main()
