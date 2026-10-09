# 阅读路线：八方向锚点（首轮 2026-10-08）

> 截止日期：2026-10-08。分层：先读「必修 6 篇」，再按方向读「选读」。阅读深度以 research/papers.jsonl 为准（本轮多为 abstract/source_only，标注 ★ 的文章需补全文）。
> 阅读问题统一为：它主张什么？证据到哪一层？对本项目是 input / baseline / differentiator / threat？

## 必修 6 篇（决定论文叙事与基线设计）

| # | 文献 | 方向 | 为什么必修 | 阅读问题 | 状态 |
|---|---|---|---|---|---|
| 1 | Fei, Li & Ding, Neurocomputing 643:130419 (2025)：DST×安全 SLR [papers/p30@1] | G1/G6 | 证明「安全×证据理论」是窄口不是空白；本文 §2 必须对话 | 它的分类框架（4R）能否容纳治理层贡献？ | ★补全文 |
| 2 | Zhang, Nguyen, Wells & Carneiro, arXiv:2605.06028 (2026-05)：Blackwell  informativeness [papers/p10@3] | G3 | 2026 对辩论/投票的最强判决；MME 第五臂来源 | 池化后验的证据论对应物是什么？ | ★补全文 |
| 3 | PRIMEX-PEV, J. Adv. Inf. Fusion 20(2):152–171 (2025-12) [papers/p16@1] | G4 | lineage-only 最强基线权威版；MME 基线 B 的锚 | PEV 编码对 BF 质量函数如何适配/为何不适配？ | ★补全文 |
| 4 | Yu, Kallurkar & Flo, CTS 2008 [papers/p18@1] | G4 | provenance-aware D-S 直接近邻；C1 的思想出处 | 它避免 double counting 的机制与根级 exactly-once 差在哪？ | 摘要已读 |
| 5 | ISO/AWI 15066-1 + ISO 10218-1/-2:2025（iso.org）[papers/p19@1][papers/p20@1][papers/p22@1] | G5 | 引用口径修正的官方依据 | 「协作应用」定义如何影响威胁模型措辞？ | 官方页已读 |
| 6 | SCoRE arXiv:2603.24704 + joint certificate arXiv:2606.08517 [papers/p38@3][papers/p40@3] | G8 | 拒判/可用性 no-harm 的证书工具，替代自造统计 | 风险-接受-效用三重证书如何映射到 unsafe-SAFE/availability 两端？ | ★补全文 |

## 本地全文（2026-10-08 入库，related_work/）

- p10 Blackwell → `related_work/blackwell-multiagent/versions/v1/paper.pdf`（+TeX 源码）
- p38 SCoRE → `related_work/score-conformal/versions/v1/paper.pdf`（+TeX 源码）
- p40 joint certificate → `related_work/selective-crc-cert/versions/v1/paper.pdf`（+TeX 源码）
- p17 事件触发 PRIMEX → `related_work/primex-event-triggered/versions/v1/paper.pdf`（+TeX 源码）
- p36 mTSBench → `related_work/mtsbench/versions/v2/paper.pdf`（+TeX 源码）
- p37 事件级 AD 基准 → `related_work/ad-event-augmentation/versions/v1/paper.pdf`（+TeX 源码）
- p05 证据知识蒸馏 → `related_work/evidential-kd-llm/versions/v1/paper.pdf`（+TeX 源码）
- p35 数字主线 KG → `related_work/digital-thread-kg/versions/v1/paper.pdf`（PDF-only）
- **未入库**（期刊/标准，须走机构渠道读原文）：p30（Neurocomputing）、p16（JAIF）、p18（IEEE CTS）、p19/p20/p22（ISO 标准）。
- 每篇附 `manifest.json`（含逐文件 SHA-256）；引用抽段须对照 pinned PDF/raw，`source/clean` 仅为检索辅助。抓取工具见 handoff.md 的 Windows 兼容说明。

## 按方向选读

- **G1**：Tang 2026（网络可靠性）[papers/p02@1]；Lu & Zhu 2026（OWA 软似然）[papers/p03@1]；arXiv:2608.13108（混沌冲突）[papers/p01@1]；兵器装备工程学报 2026（BPA 未知项语义）[papers/p04@1]。目的：掌握冲突度量的最新族，判断能否作为「组内池化」的替代算子写进相关工作。
- **G2**：arXiv:2507.18366（evidential 蒸馏）[papers/p05@3]；ICLR 2026 DRO-evidential 集成 [papers/p06@1]；ETN 2026 [papers/p07@1]；EvidentialRAG [papers/p08@1]；awesome-EDL GitHub [papers/p09@1]。目的：为 VLM/LLM 语义证据源选校准外挂；注意多为分类任务证据。
- **G3**：KDD 2026 consensus 报告 [papers/p11@1]；When Agents Disagree [papers/p12@1]；OWASP Agentic Top 10 2026 [papers/p13@1]；Microsoft 记忆投毒实测 [papers/p14@1]；可信记忆栈综述 [papers/p15@1]。目的：把「记忆治理」纳入相关工作并设计 MME 对抗臂。
- **G5**：Schlotzhauer 2025 [papers/p24@1]；MDPI Machines 14(3):255 DT-HRCA [papers/p25@1]。目的：HRC 动态风险层定位，避免把感知/控制层当新颖性。
- **G6**：AIChE PSP prs.70040/prs.70015 [papers/p27@1][papers/p28@1]；ChatP&ID 项目页 + AIChE J 2026 [papers/p29@1]；Guo 2026 JLPPI [papers/p31@1]；LLM-HAZOP 19–37% 研究 [papers/p32@1]；Alrowaie 2026 预印本 [papers/p33@1]。目的：SafetyArtifactIR 的域内近邻与 GenAI 局限性证据。
- **G7**：arXiv:2608.24918 数字主线 KG [papers/p35@3]；mTSBench [papers/p36@3]；事件级 AD 基准 [papers/p37@3]；AAS/IEC 63278  practitioner 参考 [papers/p34@1]。目的：六源接入矩阵的标准挂接与 MME 压力测试协议借用。
- **G8**：Kwon & Kim Sci Rep 2026 临床分流 [papers/p39@1]；CanQualify/预测性安全行业材料 [papers/p41@1][papers/p42@1]（弱证据，仅作背景）。

## 阅读纪律

- 摘要证据只能写进行业地图，不能进论文主张；★ 篇未补全文前，相关句子在 v21 修正稿中须保持「待核」或删除。
- 二手来源（行业博客/媒体转述的同行评议研究）在投稿前必须回原文定位页藁，否则不进参考文献。
- 每读一篇追加 `research/papers.jsonl`（新 rev 或新 ID）与 `claims.jsonl`，运行 check-research.py --mark-review。
