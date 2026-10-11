# 研究三：观测、匹配、动作三层幂等性

## 范围

这是对现有 `AlertLedger` 的纯软件合成字符化检查，不是生产策略、用户效果或传输保证。复用的标识是 `CandidateEvent.candidate_id`、`source_id`、`evidence_refs` 和稳定 `association_id`；没有新增 dedup key、interval 或来源可信阈值。

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

最小反例是稳定卡 `CARD-A` 在同一待核期间先后触达 `A-B` 与 `A-C` 两个候选关系。若动作层按“卡 + 通知类型 + episode interval”合并，会生成一个持续更新的提醒；若按 association ID 分开，会保留两条提醒更新。当前实现选择的是后一种软件行为，但**这不等于已获业务批准**。去重 key、episode interval 起止和负担/漏报权衡待用户决定。

建议把动作处理做成卡片级幂等 upsert：在用户冻结 interval 语义后，同卡同类待核动作更新同一提醒内容修订，并累积所有 association/evidence refs；风险升级和新合格风险源仍须产生可追溯的新修订。该建议不在本轮实现，也不据此估算省下的模型调用或通知数量。

## 相邻系统设计依据

这些是一手平台文档和工程设计说明，不是对本研究效果的实验结果，也未给出本研究的正确 key：

- [Google Cloud Pub/Sub exactly-once delivery](https://docs.cloud.google.com/pubsub/docs/exactly-once-delivery)：围绕消息 ID、acknowledgment 与 redelivery 定义投递层保证；文档也区分 redelivery 与 duplicate，并说明 publish-side unique retries 可能产生不同 message IDs。
- [Confluent/Kafka exactly-once semantics](https://www.confluent.io/blog/exactly-once-semantics-are-possible-heres-how-apache-kafka-does-it/)：区分 producer idempotence、Kafka 内 read/process/write 事务，以及外部 RPC/状态副作用；Kafka 内的保证不能自动覆盖外部 side effect。
- [Stripe idempotent requests](https://docs.stripe.com/api/idempotent_requests)：以请求 key 识别同一操作的重试并复用首个执行结果，示例说明动作层幂等需要其自己的操作身份。

综合这些相邻设计，可以把观测记录、匹配关系、通知动作分开定义与测量。这是对文档范围的设计推论；不能据此把不同设备观测折叠为一个输入，也不能宣称观测层去重已令通知或真实副作用 exactly-once。

## 历史结果

旧 Mac V3-RSS 记录继续保持 1,464 项检查、整轮 `FAILED`；20 条方法记录缺少确证新事件首报，且不视作独立样本。本轮没有重跑旧试验。
