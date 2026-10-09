#!/usr/bin/env python3
"""Final v2 schema-normalized v6.6 DOCX builder."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from docx.oxml import OxmlElement
from docx.oxml.ns import qn


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "tools" / "build_experiment_start_docx_v66_release2.py"


def load_helper():
    spec = importlib.util.spec_from_file_location("v66_docx_release2", HELPER)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load release helper")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def install_shading_fix(module) -> None:
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

    module.set_cell_shading = set_cell_shading


def main() -> None:
    helper = load_helper()
    module = helper.load_base()
    helper.install_cell_margin_fix(module)
    install_shading_fix(module)
    module.build()
    helper.patch_zoom_without_namespace_loss()
    print(helper.OUT)


if __name__ == "__main__":
    main()
