from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "实验执行记录v6.7-SHK-000-远程资格启动.md"


def absolutize_links(text: str) -> str:
    pattern = re.compile(r"\]\((?!https?://|<?[A-Za-z]:/)([^)]+)\)")

    def repl(match: re.Match[str]) -> str:
        target = match.group(1)
        if target.startswith("#"):
            return match.group(0)
        absolute = (ROOT / target).resolve().as_posix()
        return f"](<{absolute}>)"

    return pattern.sub(repl, text)


def main() -> None:
    text = PATH.read_text(encoding="utf-8")
    text = text.replace("RUN_RESULT.v2.json", "RUN_RESULT.v3.json")
    text = text.replace("REMOTE_RETRIEVAL_MANIFEST.v2.json", "REMOTE_RETRIEVAL_MANIFEST.v3.json")

    anchor = "| 回收与核验清单 | [REMOTE_RETRIEVAL_MANIFEST.v3.json](outputs/remote-shakedown/SHK-000-remote-20260714T0900Z/REMOTE_RETRIEVAL_MANIFEST.v3.json) |"
    insert = anchor + "\n| 最终远端边界审计 | [FINAL_REMOTE_AUDIT.json](outputs/remote-shakedown/SHK-000-remote-20260714T0900Z/FINAL_REMOTE_AUDIT.json) |"
    if "| 最终远端边界审计 |" not in text:
        if anchor not in text:
            raise AssertionError("table anchor missing")
        text = text.replace(anchor, insert, 1)

    qa_anchor = "- `pytest`：**25 passed in 3.42s**。原始输出：[pytest.stdout.log](outputs/remote-shakedown/SHK-000-remote-20260714T0900Z/pytest.stdout.log)。"
    qa_insert = qa_anchor + "\n- `pip check`：**No broken requirements found**。原始输出：[08_pip_check.stdout.log](outputs/remote-shakedown/SHK-000-remote-20260714T0900Z/08_pip_check.stdout.log)。"
    if "No broken requirements found" not in text:
        if qa_anchor not in text:
            raise AssertionError("pytest anchor missing")
        text = text.replace(qa_anchor, qa_insert, 1)

    gate_anchor = "权威 Gate 记录见 [RUN_RESULT.v3.json](outputs/remote-shakedown/SHK-000-remote-20260714T0900Z/RUN_RESULT.v3.json) 与 [RUN_POLICY.json](deployment/v20.1-v6.7-g0g2-20260714T085552Z/package/RUN_POLICY.json)。结论是：**G1/G2 只有 narrow canary PASS，整体 Gate 没有关闭。**"
    audit_para = gate_anchor + "\n\n最终边界审计 [FINAL_REMOTE_AUDIT.json](outputs/remote-shakedown/SHK-000-remote-20260714T0900Z/FINAL_REMOTE_AUDIT.json) 记录：实际 `D_test` namespace 目录数为 0，`releases/` 条目数为 0，candidate 可写条目数为 0，`data/test` 与 `runs/confirm` 均不存在，credential literal 命中数为 0。该审计只证明本次远程操作没有越过已声明边界，不证明未来运行天然安全。"
    if "candidate 可写条目数为 0" not in text:
        if gate_anchor not in text:
            raise AssertionError("gate anchor missing")
        text = text.replace(gate_anchor, audit_para, 1)

    text = absolutize_links(text)
    PATH.write_text(text, encoding="utf-8")

    if "RUN_RESULT.v2.json" in text or "REMOTE_RETRIEVAL_MANIFEST.v2.json" in text:
        raise AssertionError("stale v2 link remains")
    if re.search(r"\]\((?!https?://|<D:/|#)", text):
        raise AssertionError("relative markdown link remains")
    print(PATH)


if __name__ == "__main__":
    main()
