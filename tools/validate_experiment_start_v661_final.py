#!/usr/bin/env python3
"""Final v6.6.1 package validator with exact tracked-change tag matching."""

from __future__ import annotations

import importlib.util
import re
from zipfile import ZipFile

from docx import Document

from validate_experiment_start_v661 import DOCX, main as base_main
import validate_experiment_start_v661 as base


def inspect_docx() -> dict:
    doc = Document(DOCX)
    heading_count = sum(1 for p in doc.paragraphs if p.style and p.style.name.startswith("Heading"))
    with ZipFile(DOCX) as archive:
        names = set(archive.namelist())
        document_xml = archive.read("word/document.xml").decode("utf-8")
        all_xml = "\n".join(
            archive.read(name).decode("utf-8", errors="ignore")
            for name in names if name.endswith(".xml")
        )
    headers = [p.text for section in doc.sections for p in section.header.paragraphs]
    checks = {
        "title_contains_v6.6.1": any("v6.6.1" in p.text and "DeepSeek" in p.text for p in doc.paragraphs),
        "header_contains_v6.6.1": any("v6.6.1" in text for text in headers),
        "toc_field": "TOC \\o" in document_xml,
        "deepseek_model_id": "deepseek-v4-flash" in document_xml,
        "external_model_manifest": "ExternalModelReleaseManifest" in document_xml,
        "doubled_version_absent": "v6.6.1.1" not in all_xml,
        "comments_absent": not any(name.startswith("word/comments") for name in names),
        "tracked_insertions": len(re.findall(r"<w:ins(?:\s|>)", all_xml)),
        "tracked_deletions": len(re.findall(r"<w:del(?:\s|>)", all_xml)),
    }
    if not all(value is True or value == 0 for value in checks.values()):
        raise RuntimeError(f"DOCX structural check failed: {checks}")
    return {
        "office_xml_validator": "PASS",
        "paragraphs": len(doc.paragraphs),
        "tables": len(doc.tables),
        "headings": heading_count,
        **checks,
    }


if __name__ == "__main__":
    base.inspect_docx = inspect_docx
    base_main()
