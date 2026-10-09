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
| `00-论文-中文阅读稿v21-*.md/.docx` | 论文现行主稿（`00-论文-中文初稿v22-*.md` 为中文扩写稿，主张以 v21 为准） |
| `实验设计与执行计划v6.8 / v6.9 / v6.10*` | 实验设计主线（v6.8 为声明主线；v6.9/v6.10 为治理链引用的后续版本） |
| `ExecutionPlan-Gates-v6.12/v6.13.md`、`GateChecklist-v6.12/v6.13.json` | 实验门禁与执行治理（机器权威） |
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
- 目录整理与归档台账：`目录整理方案与清单-20261009.md`、`archive/整理清单-20261009.csv`。
