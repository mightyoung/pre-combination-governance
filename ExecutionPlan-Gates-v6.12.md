# v6.12 两个正式实验门槛执行计划：完整方法运行时与存储/归档解锁

状态：`FORMAL_EXPERIMENT_BLOCKED`  
依据：v6.11 资源计划、SHK-001A 生成器金丝雀执行记录、本机恢复校验。  
目标：把当前项目从“只能运行非确认性 shakedown”推进到“允许启动 SHK-001B，再由 SHK-001B 实测结果决定 Phase 0 和 MME_SCREEN 是否可启动”。

本计划不改变 v6.10/v6.11 的统计设计权威：独立单位、随机化、bundle 完整性、方法面板完整性、superblock 规则、禁止 effect peeking 和 100GB 硬上限继续有效。25GB 是当前资源约束下的物理微阶段预算，不是统计设计单位。

## 1. 当前结论

SHK-001A 已通过，但它只证明生成器、隔离合同、确定性重放和跨节点恢复链路可工作。它的 ledger 状态是 `GENERATED_NOT_EXECUTED`，没有执行 B0-B5 或 Proposed，因此不能支撑任何论文实验结论。

下一步必须同时突破两个门槛：

1. 完整方法运行时门槛：实现并验证 B0-B5 + Proposed 的统一执行、事务生命周期、资源遥测、失败处理和 scorer-only 隔离。
2. 存储/归档门槛：远端可用空间达到正式微阶段启动阈值，并配置两份独立持久归档，其中至少一份为 off-host 或 off-volume 的不可变副本。

在两个门槛未通过前，只允许非确认性开发实验和接口测试；不允许启动 Phase 0 正式资格块、MME、pilot 或 confirmatory 阶段。

## 2. 门槛 A：完整方法运行时

### A0. 代码基线冻结

输入：
- `risk-fusion-bench` 当前代码。
- SHK-001A 输出和 QA 规则。
- v6.10/v6.11 的方法面板与隔离合同。

动作：
- 记录当前 candidate hash、Python 版本、依赖版本、容器或 venv 路径。
- 给运行时新增统一 manifest schema，区分 `GENERATED_NOT_EXECUTED`、`METHOD_EXECUTED_NONCONFIRMATORY`、`METHOD_EXECUTED_FORMAL`。
- 明确 SHK-001B 的输出仍为非确认性，禁止 promotion。

验收：
- 生成 `runtime_baseline.json`。
- 本地测试通过。
- 没有修改 SHK-001A 已封存输出。

### A1. MethodRegistry

动作：
- 实现一个显式 registry，包含 7 个方法臂：`B0`、`B1`、`B2`、`B3`、`B4`、`B5`、`Proposed`。
- 每个方法必须声明：输入字段白名单、输出 schema、资源限制、超时、随机种子策略、是否允许 GPU。
- registry 启动时做完整性检查：缺方法、重名、schema 不一致、方法读取禁用 truth 字段均直接 fail closed。

验收：
- `method_registry.json` 包含 7/7 方法臂。
- 单元测试覆盖 registry 枚举、重复名拒绝、禁用字段拒绝。
- 任何方法缺失时 SHK-001B 不能启动。

### A2. 事务生命周期

动作：
- 每个 `bundle_id × method_id` 形成一个事务。
- 状态机固定为：`PLANNED -> RUNNING -> SUCCEEDED|FAILED|TIMEOUT|SKIPPED_POLICY -> SEALED`。
- 每个事务写入：输入 hash、方法 hash、开始/结束时间、exit code、CPU time、RSS、可选 VRAM、stdout/stderr 摘要 hash、输出 hash。
- 中断恢复只能重跑未 sealed 事务，不能覆盖 sealed 事务。

验收：
- 28 bundle × 7 methods 在 SHK-001B 中产生 196 个事务。
- 失败、超时、重试都有可复现 ledger。
- ledger 与 manifest 双向闭合：manifest 中每个输出能回到唯一事务，事务中每个 sealed 输出能在 manifest 找到。

### A3. Scorer-only 隔离

动作：
- 方法可见 payload 继续沿用 SHK-001A 的白名单。
- truth store 只允许 scorer 读取；candidate runtime 进程不得打开 truth 路径。
- 对文件路径、环境变量、命令行参数、日志和异常文本做泄漏扫描。

验收：
- QA 明确报告 `method_visible_payload_has_no_truth_fields=true`。
- 运行时审计报告列出被拒绝字段和路径。
- 故意注入禁用字段的负测试必须失败。

### A4. 最小候选实现策略

为避免“运行时搭好了但方法只是空壳”，B0-B5 和 Proposed 的最低可接受标准如下：

- B0：单证据流或朴素风险基线，确定性输出。
- B1：规则/阈值基线。
- B2：传统统计或机器学习基线。
- B3：无分层证据融合的平面融合基线。
- B4：去除关键模块的消融基线。
- B5：强竞争融合基线，优先选与 Information Fusion 读者熟悉的可解释融合或证据理论路线。
- Proposed：论文主方法，必须暴露可审计中间量，但不能读取 truth。

验收：
- 每个方法输出同一指标接口。
- 方法输出不能是随机占位、常数占位或只复制输入字段。
- Proposed 的关键中间证据链可被 scorer 后验校验。

### A5. SHK-001B 全方法尺寸试验

启动条件：
- A1-A4 全部通过。
- 远端 free 不低于开发准入阈值 `210,000,000,000 B`。
- 单次输出预估不超过 25GB 微阶段预算。

动作：
- 使用 28 个非晋级 bundle。
- 全量执行 7 个方法臂。
- 测量每个事务的 bytes、wall time、CPU time、RSS、可选 VRAM。
- 输出 P50/P95/P99 和失败率。

验收：
- 196/196 事务有终态。
- 资源报告生成 `shk001b_sizing_report.json`。
- 更新 `ResourceStageMatrix` 的 q99 bytes/time/RAM/VRAM。
- 仍标记 `NON_CONFIRMATORY_DO_NOT_PROMOTE`。

## 3. 门槛 B：存储与归档解锁

### B0. 空间恢复目标

当前 SHK-001A 后远端 free 约 `216,624,607,232 B`。正式 25GB 微阶段启动阈值为 `265,853,007,872 B`。按当前快照，至少需要释放约 `49.23 GB`，启动前必须重新测量。

执行原则：
- 不清理未知 Docker 容器、镜像或业务目录。
- 只清理本项目明确拥有的临时文件、非确认性 scratch、可再生缓存。
- 清理前生成候选清单，清理后记录释放量和 hash/manifest 状态。

验收：
- `storage_pre_cleanup_inventory.json`。
- `storage_cleanup_ledger.json`。
- `df` 快照显示 formal free >= `265,853,007,872 B`。

### B1. Archive A

要求：
- 持久、可写、可校验。
- 不与远端 root 共享同一活动实验目录。
- 保存 manifest、ledger、sealed outputs、QA 和 checksum。

最低验收：
- 可写入 1GB 测试对象。
- 可读回并 SHA-256 匹配。
- 支持按 run id 列表化。
- 记录 URI 或挂载点，但不在论文或公开材料中暴露凭证。

### B2. Archive B

要求：
- 与 Archive A 独立。
- 至少一份归档必须 off-host 或 off-volume，并尽量设置不可变或追加式策略。

最低验收：
- 同样通过 1GB 写入、读回、hash 校验。
- 与 Archive A 的 failure domain 不同。
- 能独立完成恢复抽检。

### B3. 本机恢复缓存策略

本机 D 盘只作为滚动恢复缓存，不作为正式 Archive。当前 D 盘余量只能支撑单个 25GB 微阶段的恢复校验。

规则：
- 每次只恢复一个 microstage。
- 校验完成后保留 manifest、QA、摘要报告；大 payload 在 A/B 归档闭合后可清理本机缓存。
- C 盘禁止落实验数据。

验收：
- 本机恢复前 D 盘 free >= `75,000,000,000 B`。
- 恢复后 D 盘 free 不低于 `45,000,000,000 B`。
- 恢复校验报告 hash 与 Archive A/B 一致。

## 4. 推荐执行顺序

1. 本机实现 A1-A3：MethodRegistry、事务生命周期、隔离 QA。
2. 本机补测试：registry、ledger、manifest、truth 泄漏负测试。
3. 远端运行最小 runtime smoke：1 bundle × 7 methods，仍为非确认性。
4. 远端运行 SHK-001B：28 bundle × 7 methods，产出尺寸报告。
5. 用 SHK-001B q99 重新计算 microstage bin packing。
6. 执行存储清单，不清理未知业务资源。
7. 释放或迁移至少 49.23GB，重新测量 formal free。
8. 配置 Archive A/B，并完成 1GB 写入读回测试。
9. 做一次完整归档演练：SHK-001B 输出归档 A/B，本机恢复抽检。
10. 全部门槛通过后，才允许签署 Phase 0 或 MME_SCREEN 的正式启动令。

## 5. 停止条件

任一条件触发时停止晋级：

- MethodRegistry 少于 7 个方法臂。
- 任何方法能读取 truth store 或禁用字段。
- ledger/manifest/hash 不闭合。
- SHK-001B 输出超过 25GB 微阶段预算，且无法在不拆 bundle、不拆方法面板的前提下 bin-pack。
- 远端 free 低于 `210,000,000,000 B` 时继续跑开发实验。
- 正式启动前远端 free 低于 `265,853,007,872 B`。
- Archive A/B 任一不可写、不可读回或 hash 不匹配。
- 任何阶段出现 effect peeking、按结果选择性重跑、拆分同一 bundle 的方法面板。

## 6. 交付物清单

门槛 A 必交付：
- `runtime_baseline.json`
- `method_registry.json`
- `transaction_ledger.schema.json`
- `method_output.schema.json`
- `truth_isolation_qa.json`
- `shk001b_sizing_report.json`
- 更新后的资源矩阵

门槛 B 必交付：
- `storage_pre_cleanup_inventory.json`
- `storage_cleanup_ledger.json`
- `archive_targets.json`
- `archive_ab_write_readback_qa.json`
- `restore_sampling_qa.json`

启动正式实验前的最终签署文件：
- `FORMAL_STAGE_ADMISSION-v6.12.json`

该文件必须同时声明：
- `runtime_gate=PASS`
- `storage_gate=PASS`
- `archive_a=PASS`
- `archive_b=PASS`
- `restore_sampling=PASS`
- `effect_peeking=false`
- `formal_start_allowed=true`

## 7. 最短可执行路线

如果目标是尽快进入 IF 投稿可用实验，优先级如下：

1. 先实现运行时，不先清空间。原因是没有 SHK-001B 的 q99 尺寸，存储计划仍然只是预算，不是实测。
2. 运行时 smoke 只跑 1 bundle × 7 methods，控制在开发阈值内。
3. SHK-001B 完成后立刻冻结 q99 资源参数。
4. 再清理或迁移空间，并配置 Archive A/B。
5. 最后签署 `FORMAL_STAGE_ADMISSION-v6.12.json`，进入 Phase 0 或 MME_SCREEN。

这条路线避免把存储资源先耗在未验证的运行时上，也避免在没有完整方法面板的情况下启动任何会污染论文结论边界的实验。
