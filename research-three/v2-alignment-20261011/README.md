# 研究三 V2 对齐回合

本目录记录从 V2 公开规格 `cc6d59b88bda73381fc09d9091a224ab4155891e` 与治理实现 `214197c0370dfd60d23786884bb7ff785d8a0092` 得出的逐项状态矩阵、业务建议和一条已实际运行的合成开发场景。

- [ALIGNMENT.md](ALIGNMENT.md)：满足/不满足/未知矩阵、18 个通知字段、9 个确认字段、指标差距、证据限制与建议。
- [IDEMPOTENCY_LAYERS.md](IDEMPOTENCY_LAYERS.md)：观测重放、候选匹配、提醒动作三层的合成反例和未冻结决策。
- [visualization/synthetic-event-timeline.html](visualization/synthetic-event-timeline.html)：单文件、离线可打开的中文时间线和卡片演变图。
- [visualization/synthetic-event-data.json](visualization/synthetic-event-data.json)：该次本地 ledger 运行的脱敏合成输入、状态快照、通知和关系历史。
- [visualization/generate_synthetic_timeline.py](visualization/generate_synthetic_timeline.py)：复现数据与图的脚本。
- [visualization/idempotency-layers-comparison.html](visualization/idempotency-layers-comparison.html)：观测 / 匹配 / 通知动作层对照的离线 HTML。
- [visualization/idempotency-layers-data.json](visualization/idempotency-layers-data.json)：该受控反例的机器可读结果；历史失败只引用既有摘要，不重跑。
- [visualization/generate_idempotency_layers.py](visualization/generate_idempotency_layers.py)：复现 idempotency layer 对照。
- [visualization/notification-coalescing-experiment.html](visualization/notification-coalescing-experiment.html)：23 条顺序合成动作输入在逐关联提醒与同卡合并策略下的离线对照，附 episode/time 证据与公开 V2 字段审计。
- [visualization/notification-coalescing-experiment-data.json](visualization/notification-coalescing-experiment-data.json)：全部输入修订、提醒动作、回放结果、保留字段与未知项。19 条来自 AlertLedger 合成过渡，4 条是显式边界探针；不构成 23 个独立样本。
- [visualization/generate_notification_coalescing_experiment.py](visualization/generate_notification_coalescing_experiment.py)：重建该对照与 HTML；下层实验候选在 [`alert_action_experiment.py`](../../risk-fusion-bench/src/rfb/research/alert_action_experiment.py) 与 [`alert_action_experiment_scenarios.py`](../../risk-fusion-bench/src/rfb/research/alert_action_experiment_scenarios.py)。
- [visualization/synthetic-event-card-examples.html](visualization/synthetic-event-card-examples.html)：四个合成场景的离线卡片示例，覆盖同一报警精确重放、同卡风险升级、两个待确认 episode 最终外部确认为 SAME 或 DIFFERENT。
- [visualization/synthetic-event-card-examples.json](visualization/synthetic-event-card-examples.json)：由动作账本、身份解析和完整卡片预览实现实际生成的机器可读结果，含每次调用返回值及 source / observed / trigger-known / detected / received / identity-evidence-known / resolved 时间。
- [visualization/synthetic-event-card-examples-input.json](visualization/synthetic-event-card-examples-input.json)：可复现的显式合成输入；SAME/DIFFERENT 均是外部给定的合成身份结果。
- [visualization/generate_synthetic_event_card_examples.py](visualization/generate_synthetic_event_card_examples.py)：调用已测试的纯软件实现生成 JSON 和独立离线 HTML，并对重放、升级、时间对齐和分拆互链执行生成期断言。
- [visualization/synthetic-event-card-examples-manifest.json](visualization/synthetic-event-card-examples-manifest.json)：生成命令、输入/生成器/实现源码哈希，以及 JSON/HTML 输出哈希。
- [`alert_notification_preview.py`](../../risk-fusion-bench/src/rfb/research/alert_notification_preview.py)：依据公开 V2 固定字段构造内容预览并逐字段审计；预览未发送，schema 只验证字段存在性。
- 新增预览测试：[test_alert_notification_preview.py](../../risk-fusion-bench/tests/test_alert_notification_preview.py)。
- [HELD_OUT_TEMPORAL_PROTOCOL_DRAFT.md](HELD_OUT_TEMPORAL_PROTOCOL_DRAFT.md)：下一轮独立 held-out 时序研究的非执行协议草案。
- [IMPLEMENTATION_REVIEW_CLOSURE_20261011.md](IMPLEMENTATION_REVIEW_CLOSURE_20261011.md)：区分交接中转述的独立审查结果与本环境新运行的 focused 检查；保留旧失败与提交轨迹。
- [`frozen_prefix_adapter.py`](../../risk-fusion-bench/src/rfb/research/frozen_prefix_adapter.py) 与 [test_heldout_prefix_adapter.py](../../risk-fusion-bench/tests/test_heldout_prefix_adapter.py)：最小不可变可见前缀适配器及合成泄漏/ID 同构/字段边界测试。两个策略臂共享同一物化前缀；这不实现或评价端到端事件确证。
- [`event_card_resolution.py`](../../risk-fusion-bench/src/rfb/research/event_card_resolution.py) 与 [test_event_card_resolution.py](../../risk-fusion-bench/tests/test_event_card_resolution.py)：待确认双 episode 关系的纯函数转移；身份确证后保留或拆分展示卡，并记录时间、证据引用和双向历史链接。函数不判断真值或投递提醒。
- [`build_event_card_preview`](../../risk-fusion-bench/src/rfb/research/alert_notification_preview.py) 与 [test_event_card_integration.py](../../risk-fusion-bench/tests/test_event_card_integration.py)：把外部身份结果与动作台账修订聚合为完整的合成卡片预览，保留当前内容、全部修订、关系链接和重放审计；会拒绝身份 episode、association ID、历史候选对、确证后分卡 episode、确证时间与修订动作时间、冲突确证状态或最新关联状态不一致的组合；正式发送保持 `NOT_DELIVERED`。该集成测试也让完整的不同未来后缀通过 frozen-prefix adapter，并核对同一 `as_of` 下的台账/卡片结果一致。
- 字符化边界测试：[test_alert_governance_idempotency.py](../../risk-fusion-bench/tests/test_alert_governance_idempotency.py)。
- 新增隔离候选测试：[test_alert_action_experiment.py](../../risk-fusion-bench/tests/test_alert_action_experiment.py) 与 [test_alert_action_experiment_scenarios.py](../../risk-fusion-bench/tests/test_alert_action_experiment_scenarios.py)。
- 公开版已明确的 V2 纯映射：[alert_governance_v2.py](../../risk-fusion-bench/src/rfb/research/alert_governance_v2.py)，focused tests 在 [`test_alert_governance_v2.py`](../../risk-fusion-bench/tests/test_alert_governance_v2.py)。这些函数只映射三类触发到提醒 kind、四类单 risk flag 到 proposed severity；不定义多 flag 优先级或完整 payload。
- [MAC_PERSISTENCE_MANIFEST.json](MAC_PERSISTENCE_MANIFEST.json)：本分支公开交付物的相对路径与校验值；Mac 根路径未指定。

重生成时间线：

```sh
python research-three/v2-alignment-20261011/visualization/generate_synthetic_timeline.py
PYTHONPATH=risk-fusion-bench/src python research-three/v2-alignment-20261011/visualization/generate_idempotency_layers.py
python research-three/v2-alignment-20261011/visualization/generate_notification_coalescing_experiment.py
python research-three/v2-alignment-20261011/visualization/generate_synthetic_event_card_examples.py
```

事件卡示例由 `synthetic-event-card-examples-input.json` 驱动，使用实际 ledger/card preview 返回值生成；同一报警的第二次调用记录为精确重放，没有新增卡片修订或提醒动作。SAME/DIFFERENT 只来自合成输入中的外部身份结论，卡片与提醒始终标记 `NOT_DELIVERED`，`emitted_at` / `visible_at` 为空，业务验收与身份真值仍为 `NOT_EVALUATED`。本展示沿用范围标记 C0/I0/M0；manifest 固定输入与输出 SHA-256。此示例无需完整 Mac V2 私有规格。

上述生成脚本只构造本地合成输入并运行内存台账/对照逻辑，不连接模型、网络服务、投递适配器、设备或运行器。所有 evidence refs 均为 `synthetic://` 占位引用，没有原始物理证据正文。动作对照为每种窗口/策略输出 23 条语义修订的增量内容预览和一条精确重放审计；这些修订不是累积后的整张可见卡，历史引用被保留也不等于完整卡已展示给用户。内容标记 `PREVIEW_ONLY`，投递状态标记 `NOT_DELIVERED`。`emitted_at` 为空且未实际产生，`visible_at` 为空且未运行。当前接口不支持 `task_ids` 绑定。

动作对照中的 0 秒与 5 秒窗口、批次 ID、同卡/同类/同阶段/关联状态/实验 interval key 和候选 episode 重叠规则都只是实验参数，未获业务冻结。`display_card_id` 是展示连续性标识，不代表物理事件等价；候选 episode 作为独立节点保留，UNKNOWN 关联不会因同卡而被合并，CONFLICT_PENDING 状态变化会独立记录。每条唯一输入先追加独立卡片修订；合并仅改变合成提醒动作数。真实送达状态为 `NOT_DELIVERED`，实际可见时间未知；提醒及时性、内容完整性、事件确证准确性分别报告。该候选不改动 V1 `AlertLedger` 默认行为，也不测模型调用节省量或真实事件确证准确率。

2026-10-11 结果驱动协议修订要求 held-out 阶段先固定共同可见前缀，再单独比较动作策略；错误拆分按物理事件身份簇评分，错误确认不结束未决计时，截止未解按阶段右删失。三类结果是提醒及时性、完整卡片内容完整性、事件确证准确性，各自报告。协议与真实轨迹的本地可得性盘点见 [HELD_OUT_TEMPORAL_PROTOCOL_DRAFT.md](HELD_OUT_TEMPORAL_PROTOCOL_DRAFT.md)。前缀适配器、待确认关系转移与完整卡片集成共二十一项 focused unittest；当前交接记录另保留独立 reviewer 转述的前十四项结论；不代表 held-out、Mac、真实送达或用户可见性已验证。

内容预览覆盖单风险标记的公开 severity 映射；多 flag 输入的 `severity` 保持空值并记为待决，不作优先级排序。由于当前接口不支持 `task_ids`，预览会明确显示“任务：当前接口不支持绑定”。新增完整卡片预览聚合外部给定的 SAME/DIFFERENT 身份结果、动作台账修订、18 字段通知内容与双向历史链接；它会拒绝 ledger episode、association ID、历史完整待核候选对、确证后分卡 episode、身份确证时间早于证据时间、修订时间早于确证时间或冲突确证状态的组合，是合成软件视图，不代表已接入真实 UI 或事件真值。精确重放不增加动作或卡片修订；单 flag 升级产生独立提醒预览。`risk_basis_ids` 与关联状态只反映 synthetic 输入映射，证据资格和消息模板语义尚未验证。字段审计仍是 partial field-presence，不构成 V2 业务验收。

V2 公开来源固定在 `task/v2-public-spec-20261011` commit `cc6d59b88bda73381fc09d9091a224ab4155891e`。原始 Mac V2 包未纳入本分支；若要逐条核对其私有合同，请提供对应版本的主规格、字段/schema、指标定义，以及版本/修订清单。缺少这些文件不妨碍当前公开规格下的独立合成工作；不会据此猜测私有规则。
