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
- [`alert_notification_preview.py`](../../risk-fusion-bench/src/rfb/research/alert_notification_preview.py)：依据公开 V2 固定字段构造内容预览并逐字段审计；预览未发送，schema 只验证字段存在性。
- 新增预览测试：[test_alert_notification_preview.py](../../risk-fusion-bench/tests/test_alert_notification_preview.py)。
- [HELD_OUT_TEMPORAL_PROTOCOL_DRAFT.md](HELD_OUT_TEMPORAL_PROTOCOL_DRAFT.md)：下一轮独立 held-out 时序研究的非执行协议草案。
- [IMPLEMENTATION_REVIEW_CLOSURE_20261011.md](IMPLEMENTATION_REVIEW_CLOSURE_20261011.md)：区分交接中转述的独立审查结果与本环境新运行的 focused 检查；保留旧失败与提交轨迹。
- [`frozen_prefix_adapter.py`](../../risk-fusion-bench/src/rfb/research/frozen_prefix_adapter.py) 与 [test_heldout_prefix_adapter.py](../../risk-fusion-bench/tests/test_heldout_prefix_adapter.py)：最小不可变可见前缀适配器及合成泄漏/ID 同构/字段边界测试。两个策略臂共享同一物化前缀；这不实现或评价端到端事件确证。
- 字符化边界测试：[test_alert_governance_idempotency.py](../../risk-fusion-bench/tests/test_alert_governance_idempotency.py)。
- 新增隔离候选测试：[test_alert_action_experiment.py](../../risk-fusion-bench/tests/test_alert_action_experiment.py) 与 [test_alert_action_experiment_scenarios.py](../../risk-fusion-bench/tests/test_alert_action_experiment_scenarios.py)。
- 公开版已明确的 V2 纯映射：[alert_governance_v2.py](../../risk-fusion-bench/src/rfb/research/alert_governance_v2.py)，focused tests 在 [`test_alert_governance_v2.py`](../../risk-fusion-bench/tests/test_alert_governance_v2.py)。这些函数只映射三类触发到提醒 kind、四类单 risk flag 到 proposed severity；不定义多 flag 优先级或完整 payload。
- [MAC_PERSISTENCE_MANIFEST.json](MAC_PERSISTENCE_MANIFEST.json)：本分支公开交付物的相对路径与校验值；Mac 根路径未指定。

重生成时间线：

```sh
python research-three/v2-alignment-20261011/visualization/generate_synthetic_timeline.py
PYTHONPATH=risk-fusion-bench/src python research-three/v2-alignment-20261011/visualization/generate_idempotency_layers.py
python research-three/v2-alignment-20261011/visualization/generate_notification_coalescing_experiment.py
```

上述生成脚本只构造本地合成输入并运行内存台账/对照逻辑，不连接模型、网络服务、投递适配器、设备或运行器。所有 evidence refs 均为 `synthetic://` 占位引用，没有原始物理证据正文。动作对照为每种窗口/策略输出 23 条语义修订的增量内容预览和一条精确重放审计；这些修订不是累积后的整张可见卡，历史引用被保留也不等于完整卡已展示给用户。内容标记 `PREVIEW_ONLY`，投递状态标记 `NOT_DELIVERED`。`emitted_at` 为空且未实际产生，`visible_at` 为空且未运行。当前接口不支持 `task_ids` 绑定。

动作对照中的 0 秒与 5 秒窗口、批次 ID、同卡/同类/同阶段/关联状态/实验 interval key 和候选 episode 重叠规则都只是实验参数，未获业务冻结。`display_card_id` 是展示连续性标识，不代表物理事件等价；候选 episode 作为独立节点保留，UNKNOWN 关联不会因同卡而被合并，CONFLICT_PENDING 状态变化会独立记录。每条唯一输入先追加独立卡片修订；合并仅改变合成提醒动作数。真实送达状态为 `NOT_DELIVERED`，实际可见时间未知；提醒及时性、内容完整性、事件确证准确性分别报告。该候选不改动 V1 `AlertLedger` 默认行为，也不测模型调用节省量或真实事件确证准确率。

2026-10-11 结果驱动协议修订要求 held-out 阶段先固定共同可见前缀，再单独比较动作策略；错误拆分按物理事件身份簇评分，错误确认不结束未决计时，截止未解按阶段右删失。三类结果是提醒及时性、完整卡片内容完整性、事件确证准确性，各自报告。协议与真实轨迹的本地可得性盘点见 [HELD_OUT_TEMPORAL_PROTOCOL_DRAFT.md](HELD_OUT_TEMPORAL_PROTOCOL_DRAFT.md)。新增前缀适配器五项 focused unittest 已在本地运行通过；不代表 held-out、Mac、真实送达或用户可见性已验证。

内容预览覆盖单风险标记的公开 severity 映射；多 flag 输入的 `severity` 保持空值并记为待决，不作优先级排序。由于当前接口不支持 `task_ids`，预览会明确显示“任务：当前接口不支持绑定”。分拆预览注明独立事件卡尚未创建；真实实现需在门控通过后创建新卡并保留到原卡的历史链接。精确重放保留原内容的处理时间，并在独立审计字段记录新的重放到达时间。`risk_basis_ids` 与关联状态只反映 synthetic 输入映射，证据资格和消息模板语义尚未验证。18 个公开 V2 必填字段逐条报告存在/未知状态；这项检查属于 partial field-presence audit，不是 V2 业务验收。

V2 公开来源固定在 `task/v2-public-spec-20261011` commit `cc6d59b88bda73381fc09d9091a224ab4155891e`。原始 Mac V2 包未纳入本分支；若要逐条核对其私有合同，请提供对应版本的主规格、字段/schema、指标定义，以及版本/修订清单。缺少这些文件不妨碍当前公开规格下的独立合成工作；不会据此猜测私有规则。
