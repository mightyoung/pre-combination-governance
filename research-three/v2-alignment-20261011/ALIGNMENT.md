# 研究三：公开 V2 规格对齐矩阵

**用途：** 对照、差异记录与后续实现决策；不是 V2 实现验收或实验结果。

## 固定来源与边界

- 本轮指定对齐依据是公开分支 `task/v2-public-spec-20261011` 的固定提交 [`cc6d59b88bda73381fc09d9091a224ab4155891e`](https://github.com/mightyoung/pre-combination-governance/tree/cc6d59b88bda73381fc09d9091a224ab4155891e/research-three/v2-public-spec-20261011)，目录 `research-three/v2-public-spec-20261011/`。清单版号为 `PUBLIC_SANITIZED_EDITION_V1`，规则版号为 `STUDY3_ALERT_BUSINESS_SPEC_V2_RESULT_INFORMED`，scope 是主业务规格、部分记录 schema 和指标定义。
- 已逐一读取该目录 7 个文件：`README.md`、`REVISION.md`、`SPEC.md`、`business-spec.json`、`record-fields.schema.json`、`METRICS.md`、`PUBLIC-MANIFEST.json`。清单列出的前 6 个文件的字节数和 SHA-256 均已与固定提交逐项核对通过；清单自身明确不含 self-hash。
- 对照实现：`task/research-three-alert-governance`，提交
  [`214197c0370dfd60d23786884bb7ff785d8a0092`](https://github.com/mightyoung/pre-combination-governance/tree/214197c0370dfd60d23786884bb7ff785d8a0092)。本对齐分支从该提交独立分出。
- 公开版中的 `SPEC_ONLY_NOT_IMPLEMENTED_NOT_EVALUATED` 描述发布时状态；`business-spec.json` 另记录该发布本身不构成实现、评估或执行授权。本轮用户明确要求以此公开合同继续对齐，并授权只实现可确定的纯软件片段；这仍不代表生产部署、真实投递、旧试验重跑或 Mac 设备/清理验证已获准或完成。
- 矩阵中的“满足”仅表示当前纯软件数据/行为有明确证据；它不表示 V2 整体验收通过。`record-fields.schema.json` 明确是 partial schema，只检查必需字段存在，不冻结字段类型、时钟格式、完整业务校验或真实 SLO。

## 公开版明确规定的合同

以下内容已能从上述公开版直接确定，不依赖私有 Mac 副本：

- 三类触发常量、统一提醒类型 `PENDING_VERIFICATION_RISK_ALERT`，以及四个单独风险 flag 到应用等级的映射。
- 合成处理里“立即”指已知触发首次出现的同一 processing prefix；不得用事后才知道的 source time 倒推触发。
- 用户可见内容的最低信息、待核状态、稳定 `display_card_id`、独立候选事件节点、四种关联状态；UNKNOWN/CONFLICT 不能 union 已确证组。
- 确认所需的五类高层证据门槛、风险升级与事件身份分离，以及相同未核区间的重复更新/新冲突等建立新更新记录的高层规则。
- 18 个通知字段、9 个确认字段的名称，以及分别评价及时性、完整性、确证准确率/覆盖、错误合并/拆分、负担和控制器验收的指标族。
- 旧严格失败保持原样；新旧口径分开，不以新规格追认旧轮通过。

公开版足以支持本轮逐项对齐和确定性映射实现。完整私有 Mac V2 原文不是当前工作的一概前置；只有在用户希望还原公开版之外的私有原始规则时才需要对应的具体原文。

## 公开版刻意留空或仍需业务选择的项

| 未冻结项 | 公开版已给出的边界 | 仍缺的具体决定 |
|---|---|---|
| 同一提醒内多个风险 flag 的 severity 汇总 | 各单 flag 的 proposed severity 已列明 | 同时存在 `EXPOSURE_HIGH` 与未定冲突等多个 flag 时，选最高级、分开发送，还是其他规则；公开版未定义优先级 |
| 通知/确认 schema 的字段类型 | 18/9 个必需字段名称固定；当前只校验字段存在 | 每个字段的数据类型、枚举全集、可空规则、ID 格式和版本演进规则 |
| 生产时间语义和 SLO | 合成逻辑要求同 prefix；记录 `trigger_known_time`、`detected_at`、`emitted_at`、`visible_at`；`operational_delivery_SLO_ms` 明确为 null / 未指定 | 实际时钟源、格式/时区/可比性、真实可见回执来源、毫秒级目标值 |
| 证据资格的机器判定 | 五类高层 gate 已列明：独立合格来源、资产/任务绑定、合法时间、有效边界/一致关系证据、解决重要冲突 | 来源资格与质量的可执行判据、允许的时间区间和边界校验细则 |
| `dedup_episode_interval_key` | 同一未核区间的重复确认更新同卡；新冲突/新合格源/升级/新决定生成更新记录 | episode interval 的起止边界、key 组成、何时启动新 interval |
| 可计算的确证评价集 | 指标要求独立评价真值、覆盖/弃权/隐藏机会分层，且不得把共享模板当独立样本 | 哪些真值来源合格、机会分母和标签裁决流程；当前没有可供本轮估算的独立数据集 |

当前最关键的业务选择是多 flag 同时生效时的 severity 汇总，细节见文末建议问题。本轮新增映射函数只接受一个 flag；在此选择确认前不实现汇总规则。

## 逐项对齐

| V2 要求 | 状态 | 当前证据与差距 |
|---|---|---|
| 保留旧首报失败与旧指标，不用新口径追认通过 | 满足 | `historical-baseline.json` 保留 1,464 检查轮次失败及 20 条方法记录缺少确证新事件首报；明确这 20 条不是独立样本。没有旧原始 bundle，也未重跑。 |
| 候选输入收到时生成软件提醒记录 | 满足 | `AlertLedger.add_candidate()` 在新增候选时立即生成 `PRECAUTIONARY` 记录；这只证明函数内生成，不证明触发识别、处理前缀或用户展示。 |
| V2 三种触发常量映射到指定通知 kind | 满足 | 新增 `rfb.research.alert_governance_v2.notification_kind_for_trigger()` 映射公开定义的三种触发；这不检测触发条件，也不表示运行时已生成或展示通知。 |
| V2 的三类风险触发均进入待核提醒运行通道 | 不满足 | 现有 ledger 没有活动风险判定、缺失/拒绝边界事件的触发器，也没有 V2 通知 payload/发射流程；纯映射函数不能替代它们。 |
| “立即”按首次已知触发的同一处理 prefix 生成 | 未知 | 当前有 `observed_at` 与 `alerted_at`，没有 prefix、`trigger_known_time` 或 `detected_at`。不能从源事件时间倒推当时已知。 |
| 公开版四种单 flag → proposed severity 映射 | 满足 | 新增 `severity_for_risk_flag()` 逐项实现 `business-spec.json` 中四个单 flag 映射；未知 flag 与多 flag 输入 fail closed。它不是 V2 通知字段或序列化器。 |
| V2 通知 payload 将 severity 与风险/提醒阶段分开 | 不满足 | 当前 `alert_level` 是 PRECAUTIONARY/CONFIRMED/ESCALATED 工作流阶段；尚无 V2 payload 中独立的 `severity` 字段。不能把旧 `danger_level` 或工作流阶段改名当作 V2 severity。 |
| 多个同时有效的 risk flag 如何汇总 severity | 未知 | 公开版只列单 flag 映射，没有优先级或拆分通知规则；等待业务选择。本轮 helper 不接受多 flag。 |
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

## 后续实现建议与业务选择

1. **保留版本边界。** 本轮只新增 `alert_governance_v2.py` 中公开版已确定的触发-kind 与单 flag-severity 纯映射；旧 `AlertLedger`、旧评分器、旧失败基线未修改。V1 已有 pending、confirm、escalate、split 的纯软件链路，但其 SAME 合并的 canonical display card 与 V2 的 presentation/episode 分层仍有差异。
2. **下一步可独立实现的合同部分。** 将 V2 展示卡上下文、候选 episode 节点、关联状态和不可变分拆引用建成独立模型；UNKNOWN/CONFLICT 不合并 episode；风险升级与事件身份分离。先用公开版明确行为写测试，不改写 V1 的卡语义，也不声称 V2 payload 合格。
3. **尚需冻结后才实现的部分。** 多 flag severity 聚合、字段类型/空值、真实时钟和 visible_at 回执、SLO、证据资格的机器判据、dedup interval/key 算法，以及可评价真值/分母。没有这些选择时保留 UNKNOWN 或拒绝聚合，不用私有 Mac 原件作为笼统前置。

### 请先讨论：多 flag severity 汇总

公开版给出单 flag 等级，但未规定一个待核提醒同时含多个 flag 时如何定级。可选：

- **A（推荐）：** 单条卡片提醒取最高优先级 `CRITICAL > WARNING_RISK_UNRESOLVED > WARNING`，同时保留全部 risk basis、冲突状态和不确定原因。这样不会让高等级依据被低等级提醒覆盖。
- **B：** 每个风险依据分别产生提醒修订，使用各自公开的单 flag 等级；不设总优先级，但同一卡片可能出现并行提醒，需额外控制重复负担。

我建议 A；该排序是建议，不是公开 V2 规则，也尚未编码。请先选 A 或 B；收到选择后再逐项讨论其他未冻结项。本轮没有运行 1,464 旧试验、真实投递、模型服务或 Mac 资格/清理流程。
