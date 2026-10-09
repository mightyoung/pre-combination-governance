# 研究简报（research-brief）

- **领域边界**：面向 HRI/生产现场实时风险评估的六源（人-机-料-法-环-测）异构证据融合；方法内核为信念函数（D-S/TBM）之上的组合前治理（fusion-specific exactly-once 准入、注册表相对资格、根级贡献守恒）。
- **模式**：discover（领域发现/梳理前沿）。用户给定机制（治理层）作为待反驳先验，不作为研究边界。
- **本调研目标**：为论文方向 2 建立整体研究框架。八个追踪方向 G1–G8：理论底座（G1 依赖证据/冲突、G4 provenance×BF）、组件层（G2 EDL×LLM）、协议对撞（G3 多智能体聚合与记忆治理）、应用域与标准（G5 HRC、G6 屏障/过程安全）、数据底座（G7 本体栈与数据质量）、验证方法论（G8 前兆挖掘与选择性预测/交并检验）。每方向要求：最新进展、代表性文献与项目、核心方法对比、现存瓶颈、后续关注重点、来源与时间范围。
- **交付物**：`landscape.md`（领域地图，主交付物）、`paper-reading.md`（阅读路线）、`research/*.jsonl`（检索与证据日志）、`handoff.md`（交接与更新频率）。
- **更新频率（用户指定）**：G1/G2 月度；G3/G4 季度；G5 标准发布/修订事件驱动；G6/G7/G8 半年度。
- **数据与算力**：桌面文献调研，无训练/实验；检索工具 WebSearch/WebFetch，窗口以各条记录 searched_at 为准。
- **与论文主工程的关系**：结论供 `00-论文-中文阅读稿v21/v22` 修正使用；本目录不修改论文主工程文件。
- **已知限制**：多数文献仅读到摘要/检索片段（reading_depth=abstract 或 source_only）；GitHub awesome 列表抓取失败一次；标准以 iso.org 官方页面为准，行业媒体转述标注待核实。
- **检索截止**：2026-10-08（本轮）；下一轮 G1/G2 于 2026-11 上旬。

## 查询分析

- **问题形状**：横向型（8 个独立子问题 sq1–sq8，对应 G1–G8）。
- **核心概念与术语变体**：belief function/Dempster-Shafer/TBM；dependent/distinct evidence；cautious rule；ER rule/ER-TLD；conflict/PCR；provenance/lineage/pedigree/double counting；evidential deep learning/Dirichlet；multi-agent aggregation/debate/martingale；memory poisoning；PRIMEX/PEV；HRC/collaborative application/SSM/PFL；barrier/IPL/LOPA/HAZOP/bow-tie；AAS/SOSA/SSN/PROV-O/digital thread；sensor drift/event-level augmentation；precursor/leading indicator/near-miss；selective prediction/abstention/conformal risk control/IUT。
- **检索预算档**：每子问题 3–5 查询，合计 16 次 WebSearch + 1 次 WebFetch（失败 1 次，如实记录）。
- **停止条件**：每子问题获得 ≥3 条 2025-2026 新证据 + ≥2 条经典锚点即饱和；未穷尽，coverage_claim=bounded。
- **发现方式**：exploratory 为主；从 Fei 2025 SLR、awesome-EDL 列表、PRIMEX-PEV 官方页、iso.org 做 snowball。

## 期望交付

- **A 阅读路线**：见 `paper-reading.md`（锚点 12 篇 + 分层）。
- **B 领域地图**：见 `landscape.md`（八方向 × 五要素 + 跨方向发现）。
- **C 候选方向**：本轮不做新方向筛选；论文方向 2 已定，调研服务于其修正。三个跨方向发现见 `landscape.md` 第 10 节。
