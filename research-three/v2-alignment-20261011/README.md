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
- [visualization/notification-coalescing-experiment.html](visualization/notification-coalescing-experiment.html)：同一合成动作流在逐关联提醒与同卡合并策略下的离线对照。
- [visualization/notification-coalescing-experiment-data.json](visualization/notification-coalescing-experiment-data.json)：全部输入修订、提醒动作、回放结果、保留字段与未知项。
- [visualization/generate_notification_coalescing_experiment.py](visualization/generate_notification_coalescing_experiment.py)：重建该对照与 HTML；下层实验候选在 [`alert_action_experiment.py`](../../risk-fusion-bench/src/rfb/research/alert_action_experiment.py) 与 [`alert_action_experiment_scenarios.py`](../../risk-fusion-bench/src/rfb/research/alert_action_experiment_scenarios.py)。
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

上述生成脚本只构造本地合成输入并运行内存台账/对照逻辑，不连接模型、网络服务、投递适配器、设备或运行器。所有 evidence refs 均为 `synthetic://` 占位引用，没有原始物理证据正文。旧输出中的 SIMULATED 不表示用户实际看到提醒；新动作对照显式标记为 `NOT_DELIVERED`。

动作对照中的 0 秒与 5 秒窗口、批次 ID、同卡/同类/同阶段合并键都只是实验参数，未获业务冻结。每条唯一输入先追加独立卡片修订；合并策略只减少重复提醒动作。运行结果将送达状态记为 `NOT_DELIVERED`，实际可见时间为未知；不会据此估算模型调用节省量或真实事件确证准确率。该候选不改动 V1 `AlertLedger` 默认行为。

V2 公开来源固定在 `task/v2-public-spec-20261011` commit `cc6d59b88bda73381fc09d9091a224ab4155891e`。完整原始 Mac V2 文档不是本轮公开合同对齐的前置；尚未冻结的具体选择列于 `ALIGNMENT.md`。
