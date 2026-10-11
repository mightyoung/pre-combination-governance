# 研究三：观测、匹配、动作三层幂等性

## 范围

这是对现有 `AlertLedger` 和一个隔离提醒动作候选的纯软件合成检查，不是生产策略、用户效果或传输保证。V1 ledger 本身未增加 dedup key、interval 或来源可信阈值；提醒动作候选显式接收实验专用 `dedup_episode_interval_key` 与候选 episode IDs，二者的正式语义仍未冻结。

## 本地反例结果

| 层 | 合成扰动 | 现有 ledger 结果 | 能支持的结论 |
|---|---|---|---|
| 观测 | 同一 `candidate_id` 与完全相同内容重放 | 返回原稳定卡；不增加候选、证据引用或提醒修订 | 该精确记录在本 ledger 内幂等；不证明跨进程/持久层幂等 |
| 观测时间 | 同一 ID 的旧记录把 `observed_at` 改成“现在”重放 | 被 `candidate_id` 内容冲突拒绝；卡、关系和提醒快照不变 | 不会用重放时间刷新 `observed_at`；数据模型没有 validity/TTL 字段，不能声称 freshness 校验 |
| 互补观测 | 同一个合成关联场景中，两条不同 device/source 与 observation/candidate ID；是否同事件仍待核 | 两节点、两张稳定卡及各自 evidence refs 保留；仅进入 PENDING 关系 | 不会仅因预期同事件而把观测全删掉；source ID 不证明来源可信或统计独立 |
| 匹配 | 同一个 A-B association 再提议 | 稳定 `association_id` 返回既有 PENDING；没有新提醒修订 | 同一关系重复提议在单个内存 ledger 内幂等 |
| 动作 | 新增不同但重叠的 A-C association，仍触达 A 卡 | 卡 A 再收到一条 `IDENTITY_LINK_PENDING` 同类提醒更新，证据引用指向另一关系 | 输入重放去重不能推出匹配或提醒动作去重；动作 key/区间尚未定义 |

测试：`risk-fusion-bench/tests/test_alert_governance_idempotency.py`。展示运行：`visualization/idempotency-layers-comparison.html`；精确状态在 `visualization/idempotency-layers-data.json`，生成器为 `visualization/generate_idempotency_layers.py`。

## 未冻结规则与最小例子

最小反例是稳定卡 `CARD-A` 在同一待核期间先后触达 `A-B` 与 `A-C` 两个候选关系。若动作层按 association ID 分开，会保留每个关联的提醒动作；若同卡同类待核提醒合并，应当仍保留各自的语义修订和 association/evidence refs。V1 `AlertLedger` 默认仍按关联产生动作；本轮候选只在独立内存实验层比较，不更改该默认行为。

## 独立提醒动作对照（2026-10-11）

新增 [提醒动作对照 HTML](visualization/notification-coalescing-experiment.html) 与 [机器可读结果](visualization/notification-coalescing-experiment-data.json)，由 [生成脚本](visualization/generate_notification_coalescing_experiment.py) 使用相同输入依次运行 `PER_ASSOCIATION` 与 `CARD_COALESCE`。输入含 19 条 AlertLedger 合成过渡动作，以及 4 条明确标为边界探针的手工合成动作，总计 23 条顺序记录，不是独立样本。场景覆盖 A-B/A-C 重叠关系、窗口内升级、同卡冲突待核、反证、确认后拆分、独立事件卡、窗口边界、跨卡相同候选、同卡不同候选 episode、来源时间倒序、迟到旧观测、精确重放和冲突重放。

| 实验窗口 | 逐关联提醒动作 | 同卡合并动作 | 语义卡片修订（两策略） | 合并进已有提醒的待核更新 | 漏掉的重要更新 |
|---:|---:|---:|---:|---:|---:|
| 0 秒 | 23 | 22 | 23 / 23 | 1 | 0 |
| 5 秒 | 23 | 21 | 23 / 23 | 2 | 0 |

5 秒策略合并的两个待核更新分别发生在同一处理时刻（0 秒差）和 5 秒包含边界；越窗更新距首条提醒 6 秒，另发动作。跨 episode 探针与 A-B 提醒共享显示卡和实验 interval key，但候选 episode IDs 不重叠，故另发动作；跨卡探针即使候选 ID 与 interval key 相同也另发动作。23 条唯一语义输入均产生独立卡片修订，合并只改变合成提醒动作数。关联 ID、观测 ID、候选 episode ID、风险标记、风险依据 ID、来源、`source_time`、`observed_at` 和证据引用均保留。精确重放不刷新原修订，改写旧记录 `observed_at` 的同 ID 重放被冲突拒绝。

合并候选的实验条件为相同 `display_card_id + action_kind + risk_stage + association_state + experiment_batch_id + dedup_episode_interval_key`，并与该提醒组首条修订至少共享一个 `candidate_episode_id`；窗口按首条 `received_at` 计算且含边界。`UNKNOWN_PENDING` 与 `CONFLICT_PENDING` 作为不同动作状态；冲突更新不并入一般待核动作。该规则以及 0/5 秒窗口均不是冻结建议或生产规则。稳定显示卡只表示展示上下文，不证明事件等价；UNKNOWN 关联和候选节点不被 union。内容预览对每个窗口/策略变体输出 23 条语义修订和一条精确重放审计；每条都列出公开 V2 的 18 个必填字段状态与修订追溯。精确重放复用原修订，旧内容冲突重放没有内容预览。所有内容标记 `PREVIEW_ONLY`，动作标记 `NOT_DELIVERED`；实际 `emitted_at` 未产生、`visible_at` 未运行。输入中的 `trigger_known_time` 与 `detected_at` 是合成字段，不是运行时外部时间证据；迟到旧观测另将 `source_time`、`observed_at`、`trigger_known_time`、`detected_at`、`received_at` 设为不同值，未以处理时间替换观测时间。单 flag severity 使用公开映射，多 flag severity 置空待定、不排序。提醒及时性、内容完整性、事件确证准确性分别报告；本合成输入只检查语义内容完整性，不能测真实事件确证准确率，亦不估模型调用节省量。来源可信度/统计独立性不评估。

另有隔离回归测试验证一个不在这 23 条输入中的情形：同卡同关联组内，调用者仍标为 `ASSOCIATION_PENDING`，但单个已知风险 flag 的公开映射从 `WARNING` 升至 `CRITICAL`，CARD_COALESCE 仍产生新的模拟动作；精确重放不追加修订，同等级与 `CRITICAL` 降至 `WARNING` 对照继续走原合并路径。该守卫只识别公开单 flag 的 `WARNING→CRITICAL`，不推定多 flag 优先级，也不改写现有合成对照结果。

测试：`risk-fusion-bench/tests/test_alert_action_experiment.py`、`risk-fusion-bench/tests/test_alert_action_experiment_scenarios.py`。复现命令见 [README](README.md)。

## 相邻系统设计依据

这些是一手平台文档和工程设计说明，不是对本研究效果的实验结果，也未给出本研究的正确 key：

- [Google Cloud Pub/Sub exactly-once delivery](https://docs.cloud.google.com/pubsub/docs/exactly-once-delivery)：围绕消息 ID、acknowledgment 与 redelivery 定义投递层保证；文档也区分 redelivery 与 duplicate，并说明 publish-side unique retries 可能产生不同 message IDs。
- [Confluent/Kafka exactly-once semantics](https://www.confluent.io/blog/exactly-once-semantics-are-possible-heres-how-apache-kafka-does-it/)：区分 producer idempotence、Kafka 内 read/process/write 事务，以及外部 RPC/状态副作用；Kafka 内的保证不能自动覆盖外部 side effect。
- [Stripe idempotent requests](https://docs.stripe.com/api/idempotent_requests)：以请求 key 识别同一操作的重试并复用首个执行结果，示例说明动作层幂等需要其自己的操作身份。

综合这些相邻设计，可以把观测记录、匹配关系、通知动作分开定义与测量。这是对文档范围的设计推论；不能据此把不同设备观测折叠为一个输入，也不能宣称观测层去重已令通知或真实副作用 exactly-once。

## 历史结果

旧 Mac V3-RSS 记录继续保持 1,464 项检查、整轮 `FAILED`；20 条方法记录缺少确证新事件首报，且不视作独立样本。本轮没有重跑旧试验。
