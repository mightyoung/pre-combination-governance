# v6.13 25GB 滚动分段执行与数据集即删计划

状态：`FORMAL_EXPERIMENT_BLOCKED`  
替代：`ExecutionPlan-Gates-v6.12.md` 的存储与归档设计；v6.12 保留为历史记录，不再作为正式存储准入依据。  
目标：每个物理执行段在远端的项目占用峰值严格不超过十进制 `25,000,000,000 bytes`；段完成后删除该段数据集，只长期保留结果包、审计包与可重生成凭据。

本版不改变 v6.10/v6.11 的统计设计：独立单位、随机化、bundle 完整性、方法面板完整性、superblock 连续性、禁止 effect peeking 与选择性重跑仍然有效。物理分段只改变数据生命周期，不改变统计单位，也不允许按观察结果决定段边界。

## 1. 对 v6.12 的不留情审查

v6.12 不能直接执行，主要问题如下。

1. **目标自相矛盾。** 一边声明 25GB 微阶段预算，一边要求 Archive A/B 长期保存 `sealed outputs` 和可恢复的大 payload。它实际降低的是活动目录占用，不是总远端存储需求，更不满足“段后删数据集、只留结果”。
2. **25GB 只是一个数字，不是可执行不变量。** 没定义统计口径、采样频率、压缩前后口径、已删除但仍被进程占用的文件、`.partial`、WAL、容器临时层和同卷归档副本是否计入。任何人都可以在不同口径下宣布 PASS。
3. **删除状态机缺失。** v6.12 只有事务 `SEALED`，没有 `DATASET_PURGE_AUTHORIZED`、`DATASET_PURGED`、残留扫描和空间回收核对。所谓“可清理”不是门禁。
4. **“执行结果”没有定义。** 若不冻结最小保留集，操作者可能删掉复核所需的 score、失败码、资源遥测或版本 hash；也可能把原始 payload 改名塞进“结果”，使存储需求原地复活。
5. **双归档用错对象。** 可再生数据集没有必要做两份永久全量归档；真正需要双副本的是体积小得多的结果包与审计包。v6.12 把容灾强度花在了错误对象上。
6. **恢复测试与新目标冲突。** v6.12 要从 A/B 恢复大 payload；新目标要求 payload 不留存。正确的复现测试应是凭 seed、生成器、配置和环境摘要重新生成抽样 bundle，再比对 commitment，而不是恢复已删除数据集。
7. **崩溃窗口未封死。** 在结果刚写出、数据尚未删除或删除到一半时崩溃，会留下重复数据、半成品和不明占用。v6.12 没有孤儿扫描、幂等清理和重启判定。
8. **启动空间阈值与段内预算脱节。** `265,853,007,872 B` 是“25% 保留 + 25GB 工作集 + 5GB 漂移”的组合值，却被写成仿佛需要提前释放并长期占有 49.23GB。阈值可以保留，但必须解释为共享卷安全底线，而不是归档容量需求。
9. **SHK-001B 本身可能越界。** “28 bundles × 7 methods 一次跑完”与 25GB 限制没有证明关系。未实测 q99 前，必须允许按完整 bundle 面板切成多个物理段；禁止把 28 bundles 当作不可拆的存储单元。
10. **只写成功路径，不写证据缺失路径。** 结果包损坏、Archive B 延迟、hash 不一致、重生成抽检失败时如何处置没有清楚定义。正确行为应是保留当前段、停止下段，而不是模糊地“稍后补归档”。

## 2. 新设计的核心边界

### 2.1 三类对象

| 类别 | 内容 | 段后策略 |
|---|---|---|
| `EPHEMERAL_DATASET` | 生成的 payload、truth store、方法输入缓存、可再生中间特征、解压副本 | 结果闭合后必须删除；不得进入长期归档 |
| `TRANSIENT_RUNTIME` | `.partial`、scratch、WAL、checkpoint、retry/quarantine、临时日志 | 段闭合后删除；失败时只保留诊断摘要，不保留大对象 |
| `DURABLE_RESULT` | 方法输出、scorer 输出、失败/超时结果、聚合所需行、资源遥测、ledger、manifest、hash、版本与 seed commitment、删除 tombstone | 长期保留；Archive A/B 双副本 |

“只保留执行结果”不等于只保留一张均值表。若删除可审计的 bundle-method 结果行，论文结论将不可复核。长期保留的最细粒度必须是每个 `bundle_id × method_id × algorithm_seed` 的结果记录，但严禁包含可反推出完整原始 payload 的大字段。

### 2.2 25GB 的唯一口径

每段从 `MATERIALIZING` 到 `DATASET_PURGED` 的任意时刻都必须满足：

`B_peak = max(B_project_tree_allocated, B_filesystem_used_delta + B_owned_external_layers) <= 25,000,000,000`。

- `B_project_tree_allocated`：实验根目录在同一文件系统上的 allocated bytes，含隐藏文件、`.partial`、WAL、临时结果和同卷归档副本。
- `B_filesystem_used_delta`：相对段启动快照的文件系统已用空间增量；用于捕获已 unlink 但仍被进程占用的文件。
- `B_owned_external_layers`：由本段创建、但落在实验根目录外的容器层、临时目录或缓存。无法计量时直接 `SAFE_HALT`。
- Archive A/B 若与活动目录同卷，其写入占用计入 25GB；因此正式配置优先 off-volume/off-host。
- 容量以十进制 bytes 计，不得用 GiB 混写；压缩收益只有实际落盘后才可计入。

遥测要求：段状态转换时强制采样，运行中每 30 秒采样一次；任何采样 `>=24,000,000,000 B` 进入 `DRAIN_AND_SEAL`，禁止生成新 bundle；任何采样 `>25,000,000,000 B` 立即 `SAFE_HALT_CAP_BREACH`，本段不得晋级。

### 2.3 段内预算

| 子预算 | 上限 bytes | 说明 |
|---|---:|---|
| ephemeral dataset | 16,000,000,000 | payload、truth、输入缓存与可再生特征 |
| durable result staging | 3,000,000,000 | 结果行、score、遥测、manifest、压缩结果包 |
| scratch/partial | 2,000,000,000 | 临时文件与原子提交空间 |
| retry/quarantine/WAL | 1,000,000,000 | 恢复和失败处理 |
| emergency reserve | 3,000,000,000 | 不可分配；用于排空与封存 |
| **总计** | **25,000,000,000** | 任一子预算或总量超限均停止 |

预算不互借。若实测结果包超过 3GB，必须减小下一段的完整 bundle 数；不得吞掉应急余量。

## 3. 物理段规划

### 3.1 段的原子内容

- 一个 bundle 的全部预签方法必须在同一物理段完成；不得把同一 bundle 的方法面板拆到不同段。
- 可以把原 v6.11 的 28/24-bundle execution batch 切成更小的物理段，只要每个 bundle 完整、分配顺序预先冻结、段间不看效应结果。
- 统计上的 execution batch 与 balance superblock 继续保持原定义；若一个统计 batch 跨多个物理段，只有组成它的全部物理段均 `RECONCILED` 后，该统计 batch 才可进入分析。
- 段边界由预运行尺寸参数决定，不得由方法输赢、效应方向、失败率优劣临时决定。

### 3.2 段容量计算

在 SHK-001B 之前使用保守上界；之后冻结实测 q99：

`n_segment = max(1, floor(16e9 / q99(dataset_bytes_per_complete_bundle)))`，并同时满足：

- `n_segment × q99(result_bytes_per_complete_bundle) <= 3e9`；
- 预估总峰值 `<=22e9`，为 3GB emergency reserve 留足空间；
- 每段包含整数个完整 bundle；
- 若单个完整 bundle 的 q99 总峰值大于 22GB，G0-STAGED 失败，必须无损流式化、减少可再生冗余或更换实现，不能拆方法面板。

SHK-001B 的 28 bundles 不再要求单段完成。先运行 `1 bundle × 7 methods`，用观测值形成保守 q99 上界；随后把其余非晋级 bundles 按冻结 `n_segment` 分段执行，全部完成后统一汇总尺寸报告。

## 4. 不可跳转状态机

每个物理段必须按以下顺序：

`PLANNED → ADMITTED → MATERIALIZING → EXECUTING → RESULT_SEALED_LOCAL → RESULT_ARCHIVED_A → RESULT_ARCHIVED_B → REGEN_VERIFIED → DATASET_PURGE_AUTHORIZED → DATASET_PURGING → DATASET_PURGED → RECONCILED`

异常终态：`PAUSED_SAFE`、`SAFE_HALT_CAP_BREACH`、`INVALID_RESULT`。异常终态不得自动转入下一段。

### 4.1 ADMITTED

必须同时满足：

- 上一段为 `RECONCILED`，不存在未解释的 orphan 文件或未关闭进程；
- 当前段计划、bundle 清单、方法面板、seed commitment、代码/容器/schema hash 已冻结；
- `free_now - 25,000,000,000 - 5,000,000,000 >= 235,853,007,872`；即共享卷仍保留 25% 基线和 5GB 外部漂移 guard；
- Archive A/B 的结果包写入读回测试均为 PASS，且至少一个 failure domain 为 off-host/off-volume；
- 容量探针和 open-deleted-file 探针可用。

按当前 v6.11 快照，该式等价于启动前 free 至少 `265,853,007,872 B`。它是共享卷保护阈值，不代表每段需要 265GB，也不要求保存数据集归档。

### 4.2 RESULT_SEALED_LOCAL

段内所有计划事务必须有终态。结果包至少包含：

- 每个 bundle-method-seed 的预测/决策、scorer 指标、有效性标志、失败/超时码；
- 聚合分析所需的预签 strata/template/batch/superblock 键；
- CPU、wall time、RSS、可选 VRAM、读写 bytes；
- 输入 commitment，而非输入 payload；
- generator、candidate、method、scorer、schema、container、allocation、preregistration hashes；
- transaction ledger、expected-vs-observed counts、stdout/stderr 摘要 hash；
- 结果文件逐文件 size/SHA-256 与结果包 Merkle root；
- `contains_raw_dataset=false` 与敏感字段扫描报告。

缺任何一项都不得删除数据集。

### 4.3 RESULT_ARCHIVED_A/B

- A/B 只接收 `DURABLE_RESULT`，禁止接收 `EPHEMERAL_DATASET`。
- 两份副本均需写入、列表化、读回并逐文件校验 SHA-256/Merkle；missing、unexpected、mismatch 必须全为 0。
- 至少一份副本 off-host/off-volume 且 immutable 或 append-only。
- Archive URI、ETag/version、hash 与时间写入 ledger；凭证不得写入结果包。

### 4.4 REGEN_VERIFIED

删除前不再恢复全量数据集，而是做确定性重生成抽检：

- 每段固定抽取 `max(2, ceil(0.01 × bundles_in_segment))` 个 bundle，抽样规则在段执行前冻结；
- 用保留的 seed commitment、generator/config/container hash 重生成；
- 重生成 payload commitment 必须与原 commitment 一致，并对全部方法重放，结果 hash 或预签数值容差必须一致；
- 抽检失败则 `INVALID_RESULT`，保留当前数据集用于诊断，禁止删除和启动下一段。

### 4.5 DATASET_PURGE_AUTHORIZED

只有以下条件全真才授权删除：

- `result_sealed_local=PASS`；
- `result_archive_a=PASS` 且 `result_archive_b=PASS`；
- `regen_verified=PASS`；
- `contains_raw_dataset=false`；
- scorer-only truth 隔离和泄漏扫描 PASS；
- DS 与 STAT 双签；自动化签名可以记录，但不能替代角色签名。

### 4.6 DATASET_PURGED 与 RECONCILED

删除范围必须来自 manifest 的 allowlist，不得使用宽泛 glob。删除：payload、truth、输入缓存、可再生中间特征、scratch、partial、checkpoint、retry/quarantine 大对象和临时日志原文。保留：结果包、审计包、失败摘要、删除 ledger 和 tombstone。

删除后必须：

1. 杀死或确认关闭所有持有段文件句柄的进程；
2. 扫描实验根、容器临时层和已声明外部路径，`ephemeral_files_remaining=0`；
3. 检查 open-deleted files，`open_deleted_bytes=0`；
4. 记录删除对象数、逻辑 bytes、回收的文件系统 bytes、allowlist hash、操作者与时间；
5. 重新读取 A/B 结果包并抽检 hash；
6. 结果包本地工作副本可删，只保留小型索引；A/B 为长期权威副本；
7. 只有盘点差异可解释且下一段仍满足 ADMITTED 公式，才进入 `RECONCILED`。

## 5. 失败与重试

- 容量达到 24GB：停止生成新 bundle，完成当前原子写，flush ledger，尝试封存；不得边运行边删除。
- 容量超过 25GB：`SAFE_HALT_CAP_BREACH`；保存小型诊断结果，当前段作废，清理需单独授权，不能把越界段伪装成成功段。
- 单个 bundle 任一方法失败：该 bundle 全方法结果标记 incomplete，不进入分析；按冻结规则在新段重跑整个 bundle，保留失败 attempt 摘要和关联 ID。
- A/B 任一写入或 hash 失败：保留本地结果包与数据集，暂停；不得先删数据再补副本。
- 重生成抽检失败：`INVALID_RESULT`，保留数据集诊断；禁止选择性换一个 bundle 重抽。
- 删除中崩溃：重启后从 manifest allowlist 幂等继续 `DATASET_PURGING`，不得重新执行已封存事务，也不得直接宣告 `PURGED`。
- 两份结果副本均不可读：该段结果不可用；按原 allocation 整段重跑，不得挑选表现不佳或失败的 bundle。

## 6. 段间可见信息

段间只允许查看容量、文件数、hash、manifest 闭合、seed 唯一性、缺失/重复行、配额完整性、隔离 QA、资源错误、重生成一致性和删除完成性。禁止查看累计 A−baseline 方向、效应量、p/CI、winner/rank、IUT/no-harm 通过率，并禁止据此改段大小、样本量、margin、weights、templates、methods 或 noise grid。

## 7. 门槛与执行顺序

1. 冻结代码基线和 7/7 MethodRegistry；完成事务、结果 schema 和 truth 隔离负测试。
2. 实现容量探针、结果包构建器、原始数据扫描器、双结果归档、重生成抽检和 allowlist purge。
3. 运行 `1 bundle × 7 methods` 非晋级 smoke；峰值不得超过 22GB。
4. 按冻结段大小完成 SHK-001B 的 28 个非晋级 bundles；每段完成后归档结果、重生成抽检、删除数据集并 RECONCILE。
5. 冻结 q99 dataset/result/scratch/peak 参数，更新全部阶段的物理段分配。
6. Archive A/B 只预留结果包容量，不再预留全量数据集容量。
7. 完成一次“生成—执行—双结果归档—重生成—数据删除—结果复读”的全链路演练。
8. runtime、25GB、结果归档、重生成、purge 五个门槛全部 PASS 后，才可签署正式阶段启动令。

## 8. 必交付物

- `runtime_baseline.json`
- `method_registry.json`
- `transaction_ledger.schema.json`
- `method_output.schema.json`
- `durable_result_manifest.schema.json`
- `truth_isolation_qa.json`
- `capacity_telemetry.jsonl`
- `shk001b_sizing_report.json`
- `result_archive_targets.json`
- `result_archive_ab_qa.json`
- `regeneration_sampling_qa.json`
- `dataset_purge_ledger.json`
- `dataset_purge_tombstone.json`
- 更新后的段分配矩阵
- `FORMAL_STAGE_ADMISSION-v6.13.json`

最终签署必须声明：`runtime_gate=PASS`、`segment_cap_gate=PASS`、`result_archive_a=PASS`、`result_archive_b=PASS`、`regeneration_gate=PASS`、`purge_gate=PASS`、`raw_dataset_retained=false`、`effect_peeking=false`、`formal_start_allowed=true`。

## 9. 全局停止条件

- 任何方法读取 truth store 或禁用字段；
- 任何时点段峰值超过 `25,000,000,000 B`；
- 单个完整 bundle 无法在 22GB 可分配预算内执行；
- 结果包包含原始 payload/truth 或缺少 bundle-method 级结果；
- A/B 结果副本任一未闭合就删除数据；
- 重生成抽检失败仍删除数据或换样本重抽；
- purge 后仍有 ephemeral 文件、open-deleted bytes 或不明空间差异；
- 为适配容量而拆 bundle 方法面板、丢弃失败结果或按效果调整段边界；
- 任一阶段发生 effect peeking、选择性重跑或结果后修改设计。

