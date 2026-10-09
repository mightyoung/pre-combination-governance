from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "00-论文-中文阅读稿v21-生命周期一致组合前治理与IF创新主线版.md"

REPLACEMENTS = {
    "动态过程安全融合需要同时处理工艺偏离、屏障状态、报警、检维修、人工记录和派生分析 [3–6], [9–12], [24], [35], [46]。":
        "动态过程安全融合需要同时处理工艺偏离、屏障状态、报警、检维修、人工记录和派生分析 [3–7], [9–12], [24], [35], [46]。",
    "FTA、Bow-Tie、LOPA 和 HAZOP 分别表达顶事件结构、危险路径、IPL 属性和偏差语义 [1], [8], [10], [35], [47], [48], [50]。这些工件不能自动证明观测独立或 Dempster distinctness。":
        "FTA、Bow-Tie、LOPA、CCF 指南和 HAZOP 分别表达顶事件结构、危险路径、IPL 属性、共同原因与偏差语义 [1], [2], [8], [10], [35], [47–50]。证据理论也已用于表达 fault-tree 底事件的认知不确定性 [49]。这些工件不能自动证明观测独立或 Dempster distinctness。",
    "同一数值生态的两个 CSTR 只支持有限模拟域。投稿前至少需要独立 simulator、shadow 或 HIL 中一项":
        "同一数值生态的两个 CSTR 只支持有限模拟域。扩展 Tennessee Eastman 数据 [29] 可承担公开故障窗、provenance 攻击和计算压力支持，但不能证明 barrier demand。投稿前至少需要独立 simulator、shadow 或 HIL 中一项",
}


def main() -> None:
    text = PATH.read_text(encoding="utf-8")
    for old, new in REPLACEMENTS.items():
        if old not in text:
            raise AssertionError(f"missing replacement anchor: {old[:60]}")
        text = text.replace(old, new, 1)
    PATH.write_text(text, encoding="utf-8")
    print(PATH)


if __name__ == "__main__":
    main()
