# 研究三：公开 V2 规格对齐矩阵

**用途：** 对照、差异记录与后续实现决策；不是 V2 实现验收或实验结果。

## 固定来源与边界

- 公开 V2 规格：`task/v2-public-spec-20261011`，提交
  [`cc6d59b88bda73381fc09d9091a224ab4155891e`](https://github.com/mightyoung/pre-combination-governance/tree/cc6d59b88bda73381fc09d9091a224ab4155891e/research-three/v2-public-spec-20261011)。已读取目录内 7 个材料；`PUBLIC-MANIFEST.json` 列出的 6 个文件均通过字节数与 SHA-256 校验。
- 对照实现：`task/research-three-alert-governance`，提交
  [`214197c0370dfd60d23786884bb7ff785d8a0092`](https://github.com/mightyoung/pre-combination-governance/tree/214197c0370dfd60d23786884bb7ff785d8a0092)。本对齐分支从该提交独立分出。
- 公开 V2 包标明 `SPEC_ONLY_NOT_IMPLEMENTED_NOT_EVALUATED_NOT_EXECUTION_AUTHORIZATION`；其业务规格写明不授权未来实现、实验或部署。用户本轮授权了对齐与明确获准的内部改动，但没有授权运行旧试验、真实投递、Mac 清理资格验证或部署。
- 矩阵中的“满足”仅表示当前纯软件数据/行为有明确证据；它不表示 V2 整体验收通过。部分 schema 只检查字段存在，不冻结类型、时钟格式、业务有效性或真实 SLO。

## 原始 Mac V2 规格缺口与最小材料请求

当前 checkout 只有旧 V1 规格及公开的 V2 规格补充包，没有原始、完整的 Mac V2 规格及其全部引用附件。因此本矩阵只对照上述固定的公开 V2 revision，不推断原 Mac 试验规则。继续冻结实现合同所需的最小材料是：

1. 原始 Mac V2 规格包及其版本/manifest，连同规格中引用的全部 schema、指标定义和附录；只需规格材料，不需要物理试验原始 payload。
2. 旧指标的精确定义，以及候选事件身份、真值标签、确证分母/排除项规则，用于保留旧失败并建立新旧可比性。
3. 若希望按 V2 行为继续写代码，还需冻结通知/确认字段类型、枚举与空值语义，trigger-known/visible 时间来源和 SLO，证据资格门槛，以及同事件、分拆和多风险 flag 冲突规则。公开补充包尚未给出这些完整约束。

本轮可独立完成的公开规格对齐和纯软件合成可视化不依赖以上私有试验原件；完整 Mac V2 原规格到位前，具体 V2 payload 与生产侧行为仍不可验收。

## 逐项对齐

| V2 要求 | 状态 | 当前证据与差距 |
|---|---|---|
| 保留旧首报失败与旧指标，不用新口径追认通过 | 满足 | `historical-baseline.json` 保留 1,464 检查轮次失败及 20 条方法记录缺少确证新事件首报；明确这 20 条不是独立样本。没有旧原始 bundle，也未重跑。 |
| 候选输入收到时生成软件提醒记录 | 满足 | `AlertLedger.add_candidate()` 在新增候选时立即生成 `PRECAUTIONARY` 记录；这只证明函数内生成，不证明触发识别、处理前缀或用户展示。 |
| V2 的三类风险触发均进入待核提醒通道 | 不满足 | 当前覆盖候选到达和显式关联提议；没有活动风险判定、缺失/拒绝边界事件，也没有 V2 通知 `kind`。 |
| “立即”按首次已知触发的同一处理 prefix 生成 | 未知 | 当前有 `observed_at` 与 `alerted_at`，没有 prefix、`trigger_known_time` 或 `detected_at`。不能从源事件时间倒推当时已知。 |
| V2 severity 与风险状态分开，按公开映射产生 WARNING/CRITICAL | 不满足 | 当前 `alert_level` 是 PRECAUTIONARY/CONFIRMED/ESCALATED 工作流阶段；没有独立 `severity` 字段。不能把旧 `danger_level` 或工作流阶段改名当作 V2 severity。 |
| 待核提醒包含可读文本、理由、证据引用和软件生成时间 | 满足 | `AlertRecord.visible_text`、`rationale`、`evidence_refs`、`alerted_at` 已存在；真实展示时间仍缺失。 |
| 文本包含 V2 要求的设备/任务/观测、未定原因、核查动作和稳定卡链接 | 不满足 | 候选输入只有 `source_id`、summary 和候选 ID；没有 observation/device/task 绑定、具体不确定原因字段或处置动作字段，文本也不证明卡片已展示给用户。 |
| `display_card_id` 是展示连续性 ID，不代表物理事件相同 | 不满足 | 当前 SAME 关系将候选并入一个 canonical 卡；`card_for()` 返回该 canonical 卡。V2 要求把展示卡上下文与物理事件节点分开。 |
| 未确认关联不合并已确认事件组 | 满足 | `PENDING` 提议保留两张卡并分别出提醒；当前 P1 冲突检查也拒绝与 SAME/DIFFERENT 约束矛盾的确认。该实现仍没有 V2 的卡内待关联视图。 |
| V2 关联状态区分 SAME_CONFIRMED、DIFFERENT_CONFIRMED、UNKNOWN_PENDING、CONFLICT_PENDING | 不满足 | 当前状态为 `PENDING`、`CONFIRMED_SAME_EVENT`、`CONFIRMED_DISTINCT`、`SPLIT_TO_DISTINCT`，没有 `UNKNOWN_PENDING`/`CONFLICT_PENDING` 语义。 |
| 具备 V2 证据资格门控 | 不满足 | 当前只要求 `evidence_refs` 非空；不验证来源资格/质量、设备任务绑定、因果时间区间、有效边界或冲突是否已解决。引用存在不等于证据充分。 |
| 风险确认/升级独立于事件身份 | 满足 | `confirm_risk_alert()` 和 `escalate_card()` 只更新提醒阶段；身份确认不会自动将风险阶段升为 CONFIRMED。证据引用要求已测，但证据资格尚未验证。 |
| 不把“同卡”当作“同事件”，保留独立候选节点与拆分引用 | 不满足 | ledger 保留原始候选对象和关联历史，但显示卡的 `candidate_ids` 会随 SAME 组件合并；没有独立 episode ID、不可变 parent/display-card link refs。 |
| 重复提醒按 episode interval 去重并单独计负担 | 不满足 | 同 ledger 候选重放幂等；没有 `dedup_episode_interval_key`，也没有首报/重复/升级/确认更新的负担统计或持续 E1 对照。 |
| 用户可见提醒延迟按 trigger_known_time 到 visible_at 计算 | 未知 | 只有内部软件生成时间；`DeliveryStatus` 为 SIMULATED 或 NOT_DELIVERED，`delivered_at` 固定为 null，没有展示回执。 |
| 旧、新评价分开，准确率、覆盖、弃权、隐藏事件均报告 | 不满足 | 现有 scorer 可在合成 ledger 关系上算 pairwise accuracy 并单列 pending；没有 V2 的确证覆盖/延迟、合格真值来源、提醒负担或隐藏事件机会分层。 |
| 稳定卡与分拆历史在内部可追溯 | 满足 | 卡 ID 确定且原 ID 保留，关系有状态历史，当前 canonical 指针会随图变化更新。这是软件 ledger 证据，不是实际 UI 展示日志。 |
| 控制器资源与清理验收 | 未知 | 本轮没有该运行 scope 的资源、EOF、回收、权限错误或清理 receipt。 |

## V2 通知的 18 个必需字段

当前代码没有 V2 notification serializer。下表判断可否由当前模型直接提供相同语义；“内部近似值”不能冒充 partial schema 的实际序列化验证。

| 字段 | 状态 | 当前模型对照 |
|---|---|---|
| `notification_id` | 满足 | `AlertRecord.alert_id` 是稳定卡加修订号；尚无 V2 payload serializer。 |
| `kind` | 不满足 | 无通知种类字段。 |
| `severity` | 不满足 | 只有工作流 `alert_level`，语义不同。 |
| `risk_state` | 未知 | 有风险标记字符串，未定义 V2 active/unknown risk 状态语义。 |
| `risk_basis_ids` | 未知 | 有 `evidence_refs`，没有来源资格或 risk-basis 绑定。 |
| `uncertainty_reason` | 未知 | 有通用 rationale，不保证表达具体缺失/矛盾/质量不合格原因。 |
| `affected_observation_ids` | 不满足 | 无 observation ID。 |
| `display_card_id` | 满足 | `card_id` 可提供稳定卡标识；没有 V2 展示记录。 |
| `candidate_episode_ids` | 未知 | 有 candidate ID，但尚未定义为 V2 物理事件 episode ID。 |
| `association_state` | 不满足 | 当前身份状态枚举不等同 V2 状态枚举。 |
| `user_visible_message` | 满足 | 有本地生成的 `visible_text` 字符串；“可读内容”不等于真实展示。 |
| `suggested_verification_action` | 不满足 | 无动作字段。 |
| `trigger_known_time` | 不满足 | 未记录。 |
| `detected_at` | 不满足 | 未记录。 |
| `emitted_at` | 满足 | `alerted_at` 可作软件生成时刻；不能替代 trigger-known 或 visible time。 |
| `visible_at` | 不满足 | 没有展示回执，`delivered_at=null`。 |
| `content_revision` | 满足 | `revision` 存在且递增。 |
| `dedup_episode_interval_key` | 不满足 | 未定义或记录。 |

## V2 确认记录的 9 个必需字段

| 字段 | 状态 | 当前模型对照 |
|---|---|---|
| `decision_id` | 不满足 | `association_id` 标识候选对，不标识一次决定。 |
| `action_confirm_new_or_continuation_or_split` | 不满足 | 关系状态可描述 SAME/DIFFERENT/SPLIT，但没有该独立动作字段。 |
| `bound_observation_ids` | 不满足 | 不记录 observation IDs。 |
| `confirmed_episode_ids` | 未知 | candidate ID 未定义为 episode ID。 |
| `qualified_evidence_ids` | 未知 | evidence refs 未做资格验证。 |
| `source_times` | 未知 | 有 event_time，但未定义为各来源的 source_times 集合。 |
| `known_times` | 未知 | 有 observed_at，不等价于每条证据的 known_time。 |
| `supersedes_refs` | 不满足 | 关系历史有前序状态，未建立显式 supersedes 引用。 |
| `display_card_link_refs` | 未知 | 有 card/canonical IDs，没有 V2 不可变展示卡链接记录。 |

## 指标对齐

| V2 指标族 | 状态 | 证据/缺口 |
|---|---|---|
| producer 复核触发与首 reason prefix | 不满足 | 当前没有 prefix、trigger-known 或首 reason prefix 数据。 |
| 待核提醒完整性 | 不满足 | V1 的 12 字段完整度不覆盖 V2 18 字段，且无完整 V2 payload。 |
| 用户可见及时性 | 未知 | `visible_at` 与真实毫秒 SLO 未提供；不能把 `alerted_at` 当展示回执。 |
| 事件确证关系准确率 | 满足 | 仅满足当前合成 ledger pairwise scorer；它不构成 V2 真实/独立真值精确率。 |
| 确证覆盖与延迟、弃权/隐藏事件机会 | 不满足 | 没有可评价机会分母、合格真值资格与按证据可用时刻计算的延迟。 |
| 错误合并/拆分与待关联覆盖 | 未知 | 有关系图一致性单测，但无独立真值集和经验性错误率/待核时长。 |
| 稳定卡持续/分拆可追溯 | 满足 | 仅内部稳定 ID、历史及关系引用已覆盖；实际展示记录未知。 |
| 提醒负担及持续 E1 对照 | 不满足 | 没有 V2 dedup key 或相应分母。 |
| 控制器资源/清理 | 未知 | 未运行且没有 scope receipt。 |

## 明确失败与未知证据

1. V2 partial schema 要求 `visible_at`，当前记录只有 `delivered_at=None` 和
   SIMULATED/NOT_DELIVERED。缺少真实展示回执，用户可见延迟是 UNKNOWN。
2. V2 的 `operational_delivery_SLO_ms` 明确为 null，类型和时间格式也未冻结。
   V1 evaluation 中的 30 秒仅是合成示例，不能作为该 SLO。
3. 确认 API 只校验引用非空；若没有来源资格、设备/任务绑定、边界时间和
   冲突关闭证据，不能把它报告成 V2 合格确认。
4. 旧 Mac V3-RSS 1,464 检查结果保持 FAILED；本轮不读取原始 bundle、不重跑、
   不把 20 条方法记录当独立样本，也不声称已通过 Mac 清理或控制器资格。

## 具体推荐

1. **先拆模型，再迁移业务流。** 新增版本化 V2 纯软件模块，分别保存
   `DisplayCard`（展示上下文）、`Observation`、`CandidateEpisode` 与关系图。
   同一卡可挂多个独立候选；UNKNOWN/CONFLICT 关系不得 union episode。保留 V1
   scorer 与旧失败记录，避免“展示卡 = 物理事件”的兼容性假象。
2. **先冻结 severity 冲突规则。** 对单一 flag 按公开映射使用 WARNING、CRITICAL
   或 WARNING_RISK_UNRESOLVED。多个同时 flag 时，推荐
   `CRITICAL > WARNING_RISK_UNRESOLVED > WARNING`，并保留完整 risk_state 与理由；
   请先确认该组合优先级，再写入可见文本。
3. **确认门控返回三态。** 将来源资格、质量、设备/任务、source/known time、
   边界与冲突证据建成 typed evidence record。字段缺失或冲突未消解时返回
   UNKNOWN/CONFLICT_PENDING；不以非空 evidence ref 代替资格审核。
4. **冻结通知合同和时钟。** 为 18 个通知字段与 9 个确认字段补齐类型、空值、
   枚举、时区和版本规则；定义 trigger_known_time 的确定方式、同 prefix 规则、
   visible_at 回执来源及毫秒 SLO。没有 UI/投递回执时保持 UNKNOWN。
5. **预注册去重和评价。** 由业务方确定 dedup key 的 asset/task/episode interval
   范围以及重复提醒何时转为升级/更新；新指标分开报告准确率、覆盖、弃权、
   未知比例、延迟和提醒负担，旧严格首报分数继续保留。

本轮没有修改生产治理代码：V2 包显式为 SPEC_ONLY，且剩余代码差距依赖上述未
冻结类型、时间、证据资格与事件/卡片业务规则。只对既有 V1 focused suite 做本地
复验，并运行单条明确标记为合成的展示场景；未运行 1,464 旧试验、真实投递、模型
服务或 Mac 资格/清理流程。
