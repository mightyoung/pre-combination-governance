# Handoff（交接）

> 最后更新：2026-10-08 · 第 1 个窗口（首轮八方向调研完成 + 遗留项闭合 + 全文库入库 + 空目录阶段说明 + 实验前置准备）

## 这个项目是什么

为论文主工程（`00-论文-中文阅读稿v21`，方向 2：HRI 实时风险 × 人机料法环测六源证据流）提供文献追踪服务。本目录 `研究方向调研-G1-G8/` 是独立调研项目，不修改论文主工程文件。

## 已完成（2026-10-08 首轮）

- `research-brief.md`：边界、八方向 G1–G8、更新频率、检索预算。
- `landscape.md`：**主交付物**。八方向各含最新进展/代表文献/核心方法对比/现存瓶颈/后续关注重点/来源与时间范围；第 9 节三条跨方向判断；第 10 节对 v21/v22 的六条可执行修正清单。首轮遗留的未引用数字提示已修复（关键行补齐论文证据引用编号）。
- `paper-reading.md`：必修 6 篇 + 按方向选读 + 阅读纪律。
- `research/*.jsonl`：sources 43、papers 43、searches 20（q07 经 rev2 闭合为成功）、claims 10。均为 schema_version 2，阅读深度如实（多数 abstract/source_only）。
- `related_work/`：**8 篇钉版本全文已入库**（2026-10-08，共 31MB；每篇含 paper.pdf + manifest.json（含逐文件 SHA-256），其中 7 篇另含 TeX source/raw/clean）：`blackwell-multiagent/v1`、`score-conformal/v1`、`selective-crc-cert/v1`、`primex-event-triggered/v1`、`mtsbench/v2`、`ad-event-augmentation/v1`、`evidential-kd-llm/v1`、`digital-thread-kg/v1`（PDF-only）。对应来源记录已追加 rev2（material_binding + acquisition_manifest_binding）。**下载≠已读**：papers.jsonl 的 reading_depth 仍为 abstract，全文精读按 `paper-reading.md` ★ 安排。
- 用户侧《阶段调研报告-2026-10-08-G1-G8首轮.md》已输出至论文主工程根目录。
- **G1/G2 月度增量已提前执行一次**（2026-10-08，自动化运行时与手动会话并行）：新增 q21–q29、s44–s54、p44–p55、c11–c20，landscape §0/§1/§2/§9/§10 已更新（如 IEECR 量子干涉再分配、gamma-CUBV 依赖感知风险界、C-EDL/CLEAR 冲突感知校准等）。此后与全文入库工作流合并，handoffs 重编号至 rev10（并发写入冲突已修复，备份在 research/.backup-20261008/）。
- **并发写入纪律**：本项目暂不支持并行写者（Windows 无 fcntl 锁）。请在无手动会话时触发自动化，或触发前告知；若再次出现重复 rev，按 h1@10 的先例合并（备份→按序重编号→重绑哈希）。
- 校验：`check-research.py` PASS（Windows 无 fcntl，禁用 `--mark-review`；哈希绑定由 h1 最新修订维护，当前 h1@10）。

## 下一窗口必须知道的事

1. **更新频率（用户指定）**：G1/G2 月度（每月上旬）；G3/G4 季度；G5 标准事件驱动（监控 iso.org/TC 299、EU OJ、认证机构公告）；G6/G7/G8 半年度。下一轮：2026-11 上旬做 G1+G2。
2. **首轮三个最重要的发现**（详见 landscape.md 第 9 节）：
   - Blackwell 2026（p10）硬化了「辩论/投票无原理性」论证，但引入池化后竟争协议——MME 应考虑第五臂；
   - 「大模型只能是受控证据源」获三向独立证据（LLM-HAZOP 技术有效性 19–37% [papers/p32@1] / 生产记忆投毒实测 [papers/p14@1] / EDL 单趟校准 [papers/p05@3][papers/p07@1]）；
   - 拒判可证书化（SCoRE p38 / joint certificate p40）——可用性 no-harm 不必自造统计工具。
3. **标准口径已变**：ISO/TS 15066:2016 已并入 ISO 10218-1/-2:2025；ISO/AWI 15066-1 在研。**2026-10-08 核查更正**：v21/v22 现稿未引用任何 ISO 标准（50 条参考文献均无；过时引用仅存于 v12–v15.1 历史稿与 v11.1 旧配套件，v15.1 为最后含 TS 15066 的稿件）。修订期凡引入协作安全标准引用，一律直接引 ISO 10218-1/-2:2025 并注明并入史（c01 更新；详《修正执行记录-01》）。
4. **待补全文（★）**：p30（Fei 2025 SLR）、p10（Blackwell）、p16（PRIMEX-PEV）、p19/p20/p22（ISO 官方页文学）、p38+p40（conformal 证书）。补读前，v21 修正稿中相关句子保持「待核」或删除。
5. **待定位原文**：p32（LLM-HAZOP 技术有效性 19–37% 的原始研究 [papers/p32@1]）、p11/p12（KDD 2026 与 arXiv 2026-09-10 原文）、p23（TÜV 2026 审计口径的官方确认）。

6. **空目录说明（阶段设计，不是缺漏）**：`复现/`、`DataSet/` 为空目录，`experiment/` 仅含 evaluation.md、results.md 两个流程模板（`{{}}` 占位，待首版实验填充），research/ 的 assertions / experiments / opportunities / tensions / failures 五个日志为空文件。原因：复现与实验位于工作流后段（…→ 硬性关卡 → 排序 → 最小可证伪实验 → `复现/` → `experiment/`），须先过关键强基线、数据、算力、合规关卡，且已执行实验必须挂人工批准的计划（approval 由人填写）；本项目以 G1–G8 追踪为主业、当前处于「地图」阶段。`DataSet/` 与 `related_work/` 已在 .gitignore 中排除（纯本地工作区）。若后续把主工程 Phase 0（参考实现+性质测试+差分）与 MME 托管到本项目，按此落位：复现报告→`复现/<baseline>/`、实验版本→`experiment/v<N>_<改动>/`、数据集→`DataSet/`（同步 `dataset.md`）。

## 实验阶段前置（2026-10-08 完成准备，未启动）

- **数据集可得性侦察完成 → [dataset.md](dataset.md)**：10 个候选（HA4M / HM-SYNC / MECCANO / MIMII / XJTU-SY / CWRU / TEP×2 / mTSBench / SWaT）的官方渠道、许可、体量与获取难度已登记；**全部未下载**。要点：HA4M 全量 2.92 TB [sources/s56@1]（须按分包子集取用）；HM-SYNC 15.5 GB（MIT）[sources/s57@1]；MIMII ≈68 GB（CC BY-SA，可用子集；DG 版为 CC BY-NC-SA）[sources/s60@1]；TEP CC0 ≈1.8 GB（Rieth）/ ≈1.9 GB（Reinartz）；SWaT 为 iTrust 申请制（约 3 个工作日、不可再分发）。下载须过「硬性关卡」并获人工批准后执行。
- **复现候选短名单（MME 基线；未启动）**：

| # | 基线 | MME 角色 | 出处 | 公开代码（2026-10-08 核） |
|---|---|---|---|---|
| 1 | Naive 池化（平均/朴素贝叶斯，无治理） | 下界锚点 | 经典 | 自实现 |
| 2 | Event-sourced exactly-once（幂等去重+重放） | 最强工程基线（P0 威胁） | 流处理实践 | 自实现（模式成熟） |
| 3 | PRIMEX-PEV 型谱系（素指数向量 GCD/LCM） | 谱系对照 | JAIF 20(2):152-171, 2025-12 | 未发现公开代码 → 自实现 |
| 4 | Cautious rule（Denœux，含 partial 变体） | 依赖证据算子对照 | Denœux 2006/2008 | 有（Python `dst-py`；HF 参考实现） |
| 5 | PCR6（DSmT 冲突再分配） | 冲突算子对照 | Martin & Osswald | 有（R `ibelief` 包；`dst-py`） |
| 6 | ER（证据推理递归算法） | 系族对照 | Yang & Xu 2002 | 公式完整公开；未定位直接下载实现 → 自实现 |
| 7 | MA-PoP（乘积后验，第五臂候选） | 聚合协议对照 | arXiv 2605.06028 [papers/p10@3] | 论文称将公开、未见链接 → 跟进正式版，暂自实现 |

- 复现纪律：报告落 `复现/<baseline>/`；实验须挂人工批准的计划（approval 由人填）；operator-agnostic 口径（DRI/SRI/false-block/availability）由统一 harness 承担；公开实现仅作 Phase 0 差分对照，不构成「已复现」结论。

## 未解决 / 风险

- ~~GitHub awesome-EDL 抓取失败~~ 已解决：web_fetch 两次失败后，第三次经 `curl -sL raw.githubusercontent.com` 成功（48KB）。**关键发现：该列表最后更新 2025/01，已停更**——G2 月度追踪不能依赖它，须走论文检索（q07@2 已记录）。
- 多数文献止步摘要；8 篇 ★ 锚点全文已入库（related_work/，尚未精读），其余仍为摘要级。
- **Windows 抓取工具注意**：技能自带 fetch_paper.py 在本机需要两处兼容处理（① Windows 无 fcntl，锁改为 no-op；② arXiv 已将 `/e-print/` 端点规范化为 `/src/`，严格跳转检查会误报）。兼容副本已持久化在 **`.tools/fetch_paper_win.py`**（自技能脚本最小改动），用法：`python .tools/fetch_paper_win.py <arxiv_idvN> <slug> --project .`。建议下窗口向技能上游反馈该问题。
- p32/p23 为二手来源，存在被推翻可能，引用前必须回原文。
- 行业媒体流传的「ISO/TS 15066:2026 Annex C（±5N/<100ms）」未获 iso.org 确认，不得写入论文。

## 给下一窗口的第一个动作

每月上旬：追加 G1/G2 检索（各 3–5 次 WebSearch）→ 更新 landscape.md 第 1、2 节 → 追加 jsonl → 跑 `python3 <skill>/scripts/check-research.py <本项目> --mark-review` → 若有威胁新颖性的发现，立即升级并在论文主线评估中处理。
