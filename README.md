# pre-combination-governance

**面向人机交互风险实时评估的分层证据融合框架 · 组合前治理与六源证据流（人机料法环测）**

本仓库为上述研究项目的主工程目录：论文与补充材料、实验设计与门禁治理、参考实现（`risk-fusion-bench`）、
领域与文献追踪（`研究方向调研-G1-G8`）的单一权威来源。

> **当前机器权威状态**：`GateChecklist-v6.13.json` → `FORMAL_EXPERIMENT_BLOCKED`
> 正式实验尚未准入；正式准入文件 `FORMAL_STAGE_ADMISSION-v6.13.json` 不存在。
> 工程资格证据（如 SHK-000 金丝雀、运行时回归）≠ 论文结果。

## 目录导览

| 路径 | 说明 |
|---|---|
| `论文/` | 论文主稿 v21（md+docx）、v22 扩写稿、开题文档 01–06、6M 最小安全元素树、场景草案、投稿倒排计划 |
| `实验治理/` | 实验设计与执行计划 v6.8–v6.10、门禁与资源（v6.12 历史对照、`ResourceAwareExecutionPlan-v6.11.json`、`ResourceStageMatrix-v6.11.csv`、资源协同与计划修订等） |
| `记录/` | 报告与记录（Oct-8 系列、主线评审、数据集核验、SHK-000/SHK-001A 执行记录、v21 核验、整理清单等） |
| 根目录保留 | `GateChecklist-v6.13.json`、`ExecutionPlan-Gates-v6.13.md`（现行机器权威，被冻结代码按根路径读取，**勿移动**）、`AGENTS.md`、`.gitignore`、`README.md` |
| `risk-fusion-bench/` | 参考实现与门禁证据（Python ≥ 3.11；`outputs/` 为证据目录） |
| `研究方向调研-G1-G8/` | 邻近领域八方向文献追踪体系（`landscape.md` 为主交付物） |
| `dataset-validation-evidence-20260727/` | 数据集完整性核验证据 |
| `docs/`、`figures/`、`outputs/`、`tools/` | 标准与模板、图表、运行输出与工具脚本 |
| `archive/` | 历史归档（**仅本机保留，不随仓库上传**；见 `archive/README.md`） |

## 使用（参考实现）

```bash
cd risk-fusion-bench
pip install -r requirements.txt    # 需要 Python >= 3.11
python -m pytest -q
```

## 记录纪律

- 未执行的实验不得写成结果；报告须区分"文件存在 / 完整性通过 / 可运行 / 已执行 / 已验证"。
- 数据、凭据与本机工具状态不入库（详见 `.gitignore`）；工作日志见 `.workbuddy/memory/`。
- 目录整理与归档台账：`记录/目录整理方案与清单-20261009.md`、`archive/整理清单-20261009.csv`（第二轮根目录归位台账：`archive/整理清单-20261009-第二轮根目录.csv`）。
