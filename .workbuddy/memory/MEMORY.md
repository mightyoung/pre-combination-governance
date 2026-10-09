# 项目长期记忆（MEMORY.md）

> 范围：本项目（面向人机交互风险实时评估的分层证据融合框架 / 人机料法环五证据流）。只记跨窗口持久的约定与事实；日常流水见同目录日期日志。

## 项目主线约定
- 论文现行主稿：`00-论文-中文阅读稿v21-生命周期一致组合前治理与IF创新主线版.md`；`v22` 为中文扩写稿（主张以 v21 为准，工程状态按 2026-07-31 清单）。
- 2026-08-20 范围冻结：排除 ViT/Mamba/交叉注意力分类性能与 25,000 窗口分类指标；"人机料法环"仅作证据来源分类。
- 机器权威：`GateChecklist-v6.13.json`；`FORMAL_EXPERIMENT_BLOCKED`，正式准入文件 `FORMAL_STAGE_ADMISSION-v6.13.json` 不存在；工程资格证据（SHK-000 25 测试+16/16 canary、runtime 回归）≠ 论文结果。0.80→0.96 是解析反例非实验观测。
- 学术纪律（历次评审共识）：未执行实验不得写成结果；占位符未回填禁止投稿；provenance/去重/event sourcing 不单独宣称为新颖；1/δ 界是支撑性分析；版本升版走 v19 规格冻结治理（P0 反例或期刊硬约束驱动并登记）。
- 2026-09-07 评审 P0：强基线（增强 event-sourced / PRIMEX-PEV 型）可能消解融合专有创新；代码面板与文献方法须如实对应（B0=1-prod(1-s)、B4=dependence=0.70 noisy-OR、B5=Fréchet 参照不得冠文献方法之名）。

## 方向与技术路线（2026-10-08 确定）
- 方向 2 为主线：HRI 实时风险 × 人机料法环测六源证据流（72 个最小安全元素为可采集单元，"测"升格为证据质量元层）；五层架构（源适配→质量元层→模态内分析→治理准入→融合）。详见 `方向2详细展开-HRI六源证据流主线-20261008.md`。
- 修正策略：整体不回退历史版本；组件级回退 v13.1（实验-声称绑定表）与 v17.2/v18.1（SafetyArtifactIR 禁止推理三元组）回正文。
- 保底门槛：Phase 0（参考实现+性质测试+第二实现差分）+ Phase 1（MME：A vs event-sourced-exactly-once / PRIMEX-PEV 型 lineage / cautious-partial / naive，operator-agnostic 的 DRI/SRI 口径，外部 scorer-only oracle）；止损线约 4 个月。
- 实验前置（2026-10-08 侦察）：数据集可用性见 `研究方向调研-G1-G8/dataset.md`（10 候选全未下载；HA4M 全量 2.92TB 须子集、MIMII≈68GB、HM-SYNC 15.5GB MIT、TEP CC0≈1.8GB、SWaT 申请制）；MME 复现短名单见 handoff（cautious rule/PCR6 有公开实现可作差分对照；PRIMEX-PEV 型、ER、MA-PoP 未定位公开实现 → 自实现为主）。日志坑：sources 的 material_kind（pdf/xml/html）与 acquisition_state（fulltext_saved）为已保存材料专有枚举，侦察记录勿带。

## 文献追踪体系（research-workflow 技能）
- 项目目录：`研究方向调研-G1-G8/`（landscape.md 为主交付物；landscape.html 为其**离线可视化版**（2026-10-08 生成，分片合并式、全内联 SVG、零外部依赖）；landscape-plain.html 为**人话版**（速读：结论 4 条 + 八方向白话 + 动手清单 5 条）；research/*.jsonl 为证据日志；related_work/ 存放钉版本全文）。
- 频率与自动化：G1/G2 月度（每月5日09:00，自动化"cc13295e…"）；G3/G4 季度（每3个月8日09:00"f781dd16…"）；G6/G7/G8 半年度（每6个月12日09:00"b5fa1528…"）；**G5 事件驱动，无调度**（人工监控 ISO/TC 299、IEC、EU OJ、认证机构公告）。
- 工具注意：check-research.py 在 Windows 无 fcntl，**禁用 `--mark-review`**；新记录必须 schema_version:2、searched_at 带时区、papers 必填 version、claims 必填 supports_statement 与 locator.section=abstract；**绑定路径必须用正斜杠手写，禁用 os.path.join**（Windows 会产出反斜杠被拒）；批量改日志先备份（备份在 `研究方向调研-G1-G8/research/.backup-20261008/`）。
- 全文抓取：技能 fetch_paper.py 需 Windows 兼容副本 `研究方向调研-G1-G8/.tools/fetch_paper_win.py`（fcntl 锁 no-op + arXiv /e-print/→/src/ 规范化跳转放行）；用法 `python .tools/fetch_paper_win.py <arxiv_idvN> <slug> --project .`；已入库 8 篇锚点（2026-10-08）。
- **并发写入纪律：本项目不支持并行写者**（无 fcntl 锁）。触发自动化前确认无手动会话；若出现重复 rev，按 2026-10-08 先例合并（备份→按序重编号→重绑哈希）。
- 依赖级联规则：source 追加修订会触发 paper→claim→交付物引用的全链复核（需逐级重固定修订号并更新 [papers/pXX@rev] 引用）。
- **空目录属阶段设计（不是缺漏）**：`复现/`、`experiment/`（仅含两个模板）、`DataSet/` 及 research/ 的 assertions / experiments / opportunities / tensions / failures 日志为空是正常阶段状态；实验资产须过强基线/数据/算力/合规关卡、由人工批准的计划驱动后才落位（DataSet/ 与 related_work/ 在 .gitignore 排除）。详见 handoff「空目录说明」（h1@12）。

## 已核验事实（2026-10-08，引用前以此为准）
- **ISO 10218-1:2025 / -2:2025 已发布；ISO/TS 15066:2016 协作应用条款已并入其中**（不再是独立文件）；ISO/AWI 15066-1 在研（2025-06 立项）将取代 TS 15066；(EU) 2023/1230 机械法规 2027-01-20 起适用，覆盖集成 AI/ML 的机械与网络安全。**2026-10-08 核查更正**：v21/v22 现稿未引用任何 ISO 标准（50 条参考文献均无）；过时引用仅存于 v12–v15.1 历史稿与 v11.1 旧配套件（v15.1 为最后含 TS 15066 的稿件，v16 起已移除）。修订期凡引入协作安全标准引用，一律直接引 ISO 10218-1/-2:2025 并注明 TS 15066:2016 并入史（详《修正执行记录-01-引用口径核查-20261008》）。
- 行业媒体所传「ISO/TS 15066:2026 Annex C（±5N/<100ms）」未获 iso.org 确认，不得引用。
- 关键 2025-2026 文献锚点：Blackwell 多智能体（arXiv 2605.06028）、PRIMEX-PEV（JAIF 20(2):152-171, 2025-12）、Fei et al. DST×安全 SLR（Neurocomputing 643:130419, 2025）、SCoRE（arXiv 2603.24704）、joint certificate（arXiv 2606.08517）、mTSBench（arXiv 2506.21550 v2）、ChatP&ID（AIChE J 72:e70540, 2026）。
