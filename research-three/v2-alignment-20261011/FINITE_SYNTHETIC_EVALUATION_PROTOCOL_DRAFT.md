# 有限合成关联评价协议草案

**状态：** `REVIEW_DRAFT`；本协议、生成器与评分代码供审阅。未生成正式 development/held-out 数据集，未运行正式或成批方法评价；仅运行单世界合成合同测试。本文不构成预注册、盲测授权、生产规则或效果结论。

## 目的与边界

为 `time_asset_rule` 与 `multi_evidence_rule` 准备一套有限、离线、可复现的合成评价合同。每条世界轨迹先生成仅含允许观测字段的输入流；每个可见截止点只物化一次前缀，并把同一前缀和同一候选输入交给两条规则。规则输出先规范序列化并计算 SHA-256，之后评分器才接触独立 sidecar 中的世界分组、关系真值、首次充分证据时间和告警升级机会。

这只是关联提议的合成开发评价。`LINK_CANDIDATES` 仍是待确认提议，不等于身份确证；本协议中的“false merge / false split”是提议级代理指标，不代表事件身份已被合并或拆分。当前规则不产生告警动作，升级漏报因此由单独评分接口接收告警动作轨迹；未提供时输出 `NOT_EVALUATED`，不会从关联提议推断告警表现。

不加入 Dempster-Shafer，不使用模型、网络、设备、真实通知、原 1,464 项试验输入或 Mac V3-RSS 原始包。旧失败、I1 修复和修复验证保留在“历史证据”一节，不以本协议覆盖或改写。

## 固定预算与分组

| 分区 | 固定种子 | 独立 world group 数 | 四类 strata 配额 | 当前状态 |
|---|---:|---:|---:|---|
| development | `2026101101` | 12 | 每类 3 个 | 只用于协议开发；本轮只运行单世界构造性单元夹具，不做调参或汇总评价 |
| held-out | `2026101102` | 24 | 每类 6 个 | 预留；需协议审阅通过后才能生成或运行，本轮不生成、不评分、不调参 |

每个 world 最多 4 个唯一异常观测 ID、6 个唯一无序评分 pair、8 个 prefix cutoff。最多方法调用预算为 development 每臂 `12 × 8 × 6 = 576` 次、held-out 每臂 `24 × 8 × 6 = 1,152` 次；两臂合计上限分别为 1,152 与 2,304 次。这是方法调用上限，不是统计分母：每个 world 的证据/分类统计仍以 6 个唯一 pair 为全集，prefix 与规则调用都不是独立样本。

每个 world 的固定最终 cutoff 是 synthetic 起点后 120 秒；完整 cutoff 序列按所有记录的唯一 `received_at` 与该最终 cutoff 登记、排序。sidecar 保存此序列；两臂必须各自为序列中每个 cutoff 提供且只提供一项输出，`score_world()` 与聚合器都校验登记序列、实际评分序列、唯一性和 8 项上限。两臂共同删去中间 prefix 仍属无效记录，不能靠彼此相等通过检查。生成器与 trajectory 合同也拒绝异常观测 ID 超过四个；正式聚合只接受完整、平衡的 12 或 24 world split。

精确转发重放不增加唯一 observation ID、唯一 pair 或 6-pair 统计分母，但若重放有新的接收时间并登记成 prefix cutoff，就会增加方法调用。独立审阅提供的示例调用数从 44 增至 56，pair 统计分母仍为 6；这应计入最多 8 个 cutoff 的调用预算，不能说重放没有计算成本。

正式 split 的 world ID 由登记 seed、split 名称、world index 和 stratum 确定。直接生成 development/held-out world 时必须使用相应的登记 seed、预算内 index 和该 index 对应的 stratum；正式 scorer sidecar 与聚合器也校验完整的确定性 ID 集合及 ID-stratum 映射。这个约束防止任意合成样本仅靠补齐行数和配额就被标成登记 split；它不构成对伪造评分载荷的密码学认证。

两臂都固定使用同一份 `InferenceConfig()`，参数为 120 秒候选时间窗、600 秒同资产候选跨度、8 米候选半径、1 米位置余量、2.5°C 值余量。**每臂超参数搜索预算为 0**，不在 development 或 held-out 上选参。该预算相同且为零，故本协议评价当前固定配置，不评价调参后的最佳规则。任何未来调参都须另行冻结开发集目标、候选 grid 和相同的每臂预算，且 held-out 开封前完成。

种子和生成器为公开确定性材料；因此该 synthetic held-out 不是密码学封存集。它只定义与 development 不重叠的预留分区，协议禁止用其选参。若未来需要真正盲态，必须由独立保管方在本公开分区之外持有种子与 truth sidecar，且新版本不得复用本公开种子。

## Strata 与生成约束

每个 world 都有两个外部真值事件、每个事件最多一个温度与一个热像观测。四类 strata 在生成器中只用于决定合成机制，标签只写进 scorer sidecar，不进入 `ObservationRecord`、前缀或方法输出：

1. `independent_same_event`：同一事件的温度与热像观测来自两个独立 acquisition roots；另一个事件提供不同真值簇的对照。
2. `adjacent_distinct_assets`：两个真值事件的已核验资产不同，但时空观测足够接近，构成可比较的异事件候选。
3. `recovery_then_new_event`：两个真值事件位于同一已核验资产，中间出现可见 `RECOVERY`；同资产间隔仍落在固定候选跨度内，以测恢复边界分隔。
4. `dependent_replay_unknown`：包含共享 lineage root 的观测、一个精确转发重放，以及一个关系真值为 `UNKNOWN` 的可比较 pair；重放不得增加独立来源数，UNKNOWN pair 保留在 coverage 分母。

数值与时间仅作生成多样性用的合成扰动。每个 split 以自己的固定 seed 派生互不相同的 world/observation/root 不透明 ID；所有记录在同一 world 内共享 `world_group`，不同 world 间不共享事件、资产和 lineage 身份。生成器输出的 `ObservableTrajectory` 仅含 `ObservationRecord` 与完整截止时间序列；`ScorerSidecar` 单独保存 split、world group、stratum、pair truth、`first_sufficient_evidence_at`、登记的完整 cutoff 序列、评估截止点及升级机会。

事实只在其 `received_at` 与字段 `earliest_known_at` 可见后进入前缀。每个 world 至少包含一条 `earliest_known_at > actual_available_at` 的迟到事实，避免用事后 `source_time` 提前决策；`first_sufficient_evidence_at` 取所需事实实际到达/可知之后。每个截止点由同一 `freeze_observable_prefix()` 调用生成；候选 pair 由共享 `build_candidate_universe()` 生成后一次性提供给两臂。策略函数只接收 `FrozenObservablePrefix`、当前 pair 和固定配置，不接收 split、seed、stratum、world group、truth、未来 cutoff 或 sufficiency label。

## 候选全集、缺失输出与计分分母

评分用固定全集为每个 world 的 4 个唯一异常 observation ID 的全部 6 个无序 pair；它在策略输出前由生成器按观测 ID 形成，不用方法输出筛选，也不使用 truth 筛选。每一截止点另有共享的可见候选子集，来自当时的共同前缀。固定全集中当时未进入候选集的 pair 在该 cutoff 视为 `ABSTAIN`；已进入候选集的每个 pair 必须有且只有一个显式动作（动作本身可以是 `ABSTAIN`）。候选集内缺失提议、重复提议或额外提议都是无效输出，不静默转换为 `ABSTAIN`。重复/方法行不计成新样本。

最终分类统计取固定最终 cutoff 上的最后一项动作：

- `false_merge_count / different_pair_denominator`：真值 `DIFFERENT` 的 pair 中，动作是 `LINK_CANDIDATES` 的个数/比例。
- `false_split_count / same_pair_denominator`：真值 `SAME` 的 pair 中，动作是 `RETAIN_SEPARATELY` 的个数/比例。
- `coverage_count / coverage_denominator`：固定全集中动作不是 `ABSTAIN` 的 pair 数/总 pair 数；分母包含 `UNKNOWN`。
- `unknown_pair_count`、其中的非拒判数及 `LINK_CANDIDATES` / `RETAIN_SEPARATELY` / `ABSTAIN` 动作计数单独报告。UNKNOWN 不进入 false merge、false split 或决策延迟分母；不得静默删除。
- 另报 `candidate_generation_recall`：最终 cutoff 前曾进入共享可见候选集的已知 SAME pair 数/固定全集中的已知 SAME pair 数。未被任一前缀生成的 pair 对规则动作记为 `ABSTAIN`，故不会伪装成错误的明确拆分。

**显式口径修订：**较早的自主关联计划曾草拟让 false merge 与 false split 都除以完整六 pair 固定全集。本版 `finite-score-v1` 改为分别除以 `DIFFERENT` 与 `SAME` 类 pair 数，使两项成为类条件错误率；`coverage` 仍用包含 UNKNOWN 的完整六 pair 分母。该定义差异保留在历史计划中，但两版比率不可直接数值比较；此修订没有基于正式 held-out 输出做选择，本草案需先经审阅冻结。

## 可解释范围

这套输入是有限脚本化开发比较，不是事件识别的通用效能证明。合成潜在 event 虽不直接传给规则，但当前可见资产与恢复线索大多能解释生成真值，数值/时间扰动也未系统覆盖决策阈值附近的困难样本。`dependent_replay_unknown` 中的 UNKNOWN 是把已知合成事件关系标签人工遮蔽，用于检查分母与动作统计；它不证明系统能识别现实中的不可辨事件。

SAME pair 的证据后延迟只对至少两个独立 lineage root 的佐证有定义。共享 root 的 SAME pair 保持在证据前右删失中；因此不能据此推断多证据方法较快。预期可冻结的结论仅限于固定脚本场景下的分支行为、候选覆盖和动作/分母处理。不得把差异解释为一般效果、真实事件确证能力或生产收益；不得为了得到优势而更换样本、阈值或 cutoff。

每项输出分子、分母、world group 数与逐 world 汇总。公布 pooled pair counts 仅作描述；跨 world 的主汇总等权计算 world 级比例，并单列可评价 world 数。pair、prefix、方法臂均不是独立样本。协议不做显著性检验，不把多个时间点或两个方法行当独立观测。

## 首次决策时间与右删失

scorer sidecar 为每个可评的 SAME/DIFFERENT pair 提供独立 `first_sufficient_evidence_at`；时间不得早于构成该结论所需的事实实际可知时间。UNKNOWN 或在 cutoff 前始终没有充分证据的 pair 不进入证据后延迟分母。

逐 pair 记录首个进入共享候选集时间、首个非 `ABSTAIN` 决策时间、首次在充分证据之后且与真值相符的决策时间、固定评价截止时间。SAME pair 的“充分证据”端点要求至少两个独立 acquisition roots 提供佐证；共享 root 的 SAME 真值 pair 没有此端点，记为证据前右删失，不进入证据后决策延迟。错误的早期决策不结束计时；只将 cutoff 前首次正确且晚于/等于充分证据时间的决策记为事件。未发生时，记录 `event_observed=false`、`duration_seconds=cutoff-first_sufficient_evidence_at`，作为证据后阶段右删失；充分证据未在截止前出现时，另记证据前右删失。错误和拒判数量仍按各自分类指标计数，不能由删失掩盖。因此这些延迟端点不能用来声称多证据规则更快。

实现返回每个 pair 的观测/删失记录与分阶段计数；不拟合 Kaplan-Meier、生存模型或将 cutoff 当作解决时间。未来若需生存估计，须先另行提交分析计划。

## 告警升级漏报（单独指标）

生成器 sidecar 可记录由公开单 flag 映射定义的升级机会：同一观测从 `EXPOSURE`（`WARNING`）变为可见的 `EXPOSURE_HIGH`（`CRITICAL`），并保存新 flag 最早已知时间与固定 world cutoff。不得用多 flag 优先级；该规则仍为 `UNDECIDED`。

`score_alert_escalation_misses()` 只接受单独的 alert action trace。某机会若 cutoff 前没有在该触发观测之后作出的 `CRITICAL` 动作，计为漏报；同时报告机会数、漏报数与从新 flag 已知至内部决策的延迟，不设 SLO/业务阈值。当前两条关联规则没有 alert action 输出，故其默认结果必须是 `status=NOT_EVALUATED`、`denominator=0`、rate 为 `null`。不得用 `LINK_CANDIDATES` 或 `RETAIN_SEPARATELY` 代替告警动作。

## 停止条件与准入

以下任一情况都停止整轮并标记 `INVALID_RUN`，不得挑选有效子集继续：

1. truth、world/split/stratum ID、未来 cutoff、首次充分证据时间或升级机会字段进入方法输入或冻结方法输出。
2. 两臂在任一 cutoff 接收的前缀哈希或候选 pair 集不完全一致。
3. 观测时间越界、world/root 跨组复用、异常观测 ID、cutoff、候选、pair truth 或 scorer 输出超出/少于固定预算，或 scorer 输出哈希校验失败。
4. 精确 replay 增加唯一观测/pair 数，或同 lineage root 被记为多个独立根。
5. UNKNOWN 被计入 false merge/split，或 coverage 分母未包括 UNKNOWN。
6. 首次错误决策被用于结束有效决策延迟，或截止未解决被误记为已解决。
7. held-out 生成/执行时协议仍为 `REVIEW_DRAFT`，配置与代码 SHA 未冻结，或发生任何基于 held-out 结果的选参/改代码。
8. 正式聚合缺少完整注册 world 数、精确 seed 派生 world ID 集合、ID-stratum 映射、四类 strata 配额平衡或共同 evaluation cutoff，或将 development 与 held-out 混合。
9. 任一方法的实际 cutoff trace 与 sidecar 登记序列不完全相同、包含重复 cutoff、超过八项，或在 world score/aggregation 中缺少该完整 trace。
10. 任一 cutoff 的候选集与提议输出不完全相同；候选集内有缺失/重复提议或输出额外 pair。

正式 held-out 还需单独批次批准。若 integrity 检查失败，保留全部失败输出和日志；不得用同一种子重新抽取并称为一次新独立评价。需要修复时须先修代码、留 RED→GREEN 证据，再以新协议版本及新 holdout seed 重新送审。

## 历史失败与修复证据

- Mac V3-RSS 历史单次试验：1,464 项检查执行完成，但整轮失败；五个合成场景、四个方法均缺少确证新事件首报。20 条方法记录不是 20 个独立样本。该失败不被本协议重跑或改写。
- I1 时间前缀泄漏修复：先行负例实测 7 项失败；`FrozenObservablePrefix` 直接构造/`dataclasses.replace` 与候选/规则消费入口随后全部验证记录级 ID、receipt 与字段可见时间。修复提交 `29095d8e127c99dd9d397a3e70b3a85a1325d0d5`，合法 ID availability 正向断言提交 `4ae8a475cd0dd0462406c8f2fd6582b110ccf5fd`，清单/证据提交 `dadffcd513ef9ebc0df2c4a9d8bf137531b565ff`。
- 该修复任务本地运行过 20 项 observable association 与 29 项 ledger focused tests。用户随后转述对 `dadffcd` 的独立复验：20+29 通过；10 个追加负例都以 `ValueError` 拒绝；合法 factory/direct/向后 replace 路径仍可得到一次 LINK、`root_count=2`，同 cutoff 输出 hash 一致。该转述没有附原始日志，本轮将其标为独立复验摘要，不冒充当前会话重跑。
- 额外独立评价审阅报告：删去完整七-cutoff trace 的中间 prefix、只留一个 cutoff 后，两臂因仍彼此相同而被 scorer 接受；报告的证据后延迟由 0 秒变为 83/96 秒，证据前右删失由 105 秒变为 0。该数值为用户转述的复现，不是本轮测试输出。本轮在独立 contract fixture 上另加完整 trace 拒绝测试。
- 本协议实现只允许单世界构造性测试与 development generator contract test。本轮不生成 12 个 development worlds、不搜索参数、不生成或评分 24 个 held-out worlds。

## 离线实现与构造性检查

- `risk-fusion-bench/src/rfb/research/observable_association_evaluation.py`：固定 split 预算/seed、严格四个异常 ID/world 合同、登记 seed/index/stratum/world ID 绑定、完整 cutoff trace 绑定与聚合边界、完整平衡 split 聚合、纯函数 world generator、共同前缀候选构造、两臂冻结运行、pair 分类/时序评分、UNKNOWN 动作分布与独立升级评分。
- `risk-fusion-bench/tests/test_observable_association_evaluation.py`：11 个构造性用例，主要使用 `CONTRACT_TEST` world；覆盖双方共同删 prefix、9 cutoff、聚合侧不完整/超额 trace、共享-root SAME 的证据前删失、候选提议覆盖，以及此前的标签隔离、UNKNOWN 分母、时间和升级口径。不生成或评分正式 split。
- 构造性测试不得调用 `generate_protocol_split("heldout")`；holdout split API 默认拒绝，只有显式 `protocol_approved=True` 才允许之后单独生成。该参数是工作流闸门，不是安全边界。
- 允许的本地验证命令：`PYTHONPATH=src python -m unittest -v tests.test_observable_association_evaluation`，从 `risk-fusion-bench/` 运行。本轮不运行 formal held-out、旧 1,464 试验、宽泛研究套件、模型/网络、设备、通知或执行器路径。

## 实施步骤

1. 先写上述 scorer 与 generator 合同的单元测试，确认缺少模块时按预期失败。
2. 实现最小、无 I/O 的数据类型、seed 派生、synthetic generator、split gate 与 scorer；只依赖标准库及既有 `observable_association`。
3. 仅运行构造性测试、现有 association focused tests，核对输出/sidecar 隔离与预算边界；更新 README/持久化 manifest，独立审查后推送本分支并读回 SHA。
4. 审阅前不生成完整 development/held-out split，不运行策略评分批次，不据此调参或宣称效果。
