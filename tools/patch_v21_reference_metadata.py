from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "00-论文-中文阅读稿v21-生命周期一致组合前治理与IF创新主线版.md"

REPLACEMENTS = {
    "IEC, Geneva, 2017.": "IEC, Geneva, 2017. https://webstore.iec.ch/en/publication/61289.",
    "IEC, Geneva, 2010.": "IEC, Geneva, 2010. https://webstore.iec.ch/en/publication/5520.",
    "IEC, Geneva, 2016.": "IEC, Geneva, 2016. https://webstore.iec.ch/en/publication/24321.",
    "Wiley-AIChE, Hoboken, 2018.": "Wiley-AIChE, Hoboken, 2018. https://doi.org/10.1002/9781119490357.",
    "U.S. Nuclear Regulatory Commission, Washington, DC, 1981.": "U.S. Nuclear Regulatory Commission, Washington, DC, 1981. https://www.nrc.gov/reading-rm/doc-collections/nuregs/staff/sr0492/index.",
    "Wiley-AIChE, Hoboken, 2015.": "Wiley-AIChE, Hoboken, 2015. https://doi.org/10.1002/9781118948743.",
}


def main() -> None:
    text = PATH.read_text(encoding="utf-8")
    for old, new in REPLACEMENTS.items():
        if new in text:
            continue
        if old not in text:
            raise AssertionError(f"missing reference anchor: {old}")
        text = text.replace(old, new, 1)
    PATH.write_text(text, encoding="utf-8")
    print(PATH)


if __name__ == "__main__":
    main()
