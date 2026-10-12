# 合成通知版本顺序边界检查

时间、版本与到达序对照见 [`ORDERING_TIMELINE.svg`](ORDERING_TIMELINE.svg)；冻结输入见 [`INPUT_AND_EXPECTATIONS.json`](INPUT_AND_EXPECTATIONS.json)，逐步机器结果见 [`RESULT.json`](RESULT.json)。

## 冻结前提

输入和正反例预期在任何本轮机制运行前冻结，记录于提交 `c2cff355c355506d29c0d0905169f3149d789f4c`。该夹具把三个概念明确分开：

- `event_occurred_at`：合成来源记录的发生时间；
- `notice_version`：夹具假设的卡片级逻辑版本，较高版本胜出；
- `received_at_processing_time`：台账收到并处理该消息的时间。

这些版本规则只是本地边界检查合同，不是私有 V2 的解释或生产规则。本次不据合成时间判断实际时钟偏差。

## 对照结果

冻结到达序是：版本 `1 → 3 → 2 → 3 → 1`，发生时间偏移 `0s → 2s → 1s → 2s → 0s`，到达时间偏移 `0s → 3s → 4s → 5s → 6s`。其中 v2 更正的发生时间早于取消 v3，但到达更晚。

| 到达步 | 消息 | 版本 | 发生 / 到达 | 版本门控 | 版本门控卡状态 / 动作数 | 无版本卡状态 / 动作数 |
| --- | --- | ---: | --- | --- | --- | --- |
| 1 | 初始提醒 | 1 | 0s / 0s | `EMITTED` | `ACTIVE` / 1 | `ACTIVE` / 1 |
| 2 | 取消 | 3 | 2s / 3s | `EMITTED` | `CANCELLED` / 2 | `CANCELLED` / 2 |
| 3 | 迟到更正 | 2 | 1s / 4s | `STALE_NOTICE_VERSION_IGNORED` | `CANCELLED` / 2 | `CORRECTED` / 3 |
| 4 | 新收据的重复取消 | 3 | 2s / 5s | `DUPLICATE_NOTICE_VERSION_IGNORED` | `CANCELLED` / 2 | `CANCELLED` / 4 |
| 5 | 取消后的旧 ACTIVE 消息重送 | 1 | 0s / 6s | `STALE_NOTICE_VERSION_IGNORED` | `CANCELLED` / 2 | `ACTIVE` / 5 |

冻结前记录的无版本旧路径反例与本轮版本门控对照均符合各自冻结预期。旧路径确实按到达顺序应用每条新 `intent_id`：迟到 v2 更正把状态从 `CANCELLED` 回退为 `CORRECTED`；重复取消增加一个通知动作；旧 v1 提醒最后把状态恢复为 `ACTIVE`。版本门控保留所有三次忽略决定及其发生/到达时间作为审计行，但不增加卡片修订或通知。最终只保留 v1 初始提醒和 v3 取消两条内容修订。

## 实现与验证

实现为 `ActionIntent` 增加可选 `notice_version`，并让实验台账按显示卡记录已接受版本：语义相同的同版本新收据去重；低于已接受最高版本的消息记录为过期并忽略。卡片修订预览记录版本号。未提供版本的现有实验调用保留原有路径，便于比较旧反例。

新用例先红灯：在实现前明确失败于 `ActionIntent` 没有 `notice_version` 字段。实现后，同一用例通过。已提交代码上运行两个隔离测试模块：

```text
PYTHONPATH=src python -m unittest -v tests.test_alert_action_experiment tests.test_event_card_integration
```

结果为 27 项通过，0 失败、0 错误。此前 26 项生命周期实验结果、Mac V3-RSS 的 1,464 项失败记录和原指标均保持原样；没有重跑旧冻结试验、调用网络/CAP 或模型服务、发送通知、做 Mac 执行器资格探测，也没有修改正在进行的独立评审或站点报告。

## 限制与下一步

该结果只检验给定合成版本合同下的台账行为。它不验证版本号由谁分配、版本冲突如何裁决、真实时间戳是否准确、版本化与未版本化消息混流、取消后如何重新开启、事件真值、来源独立性、真实投递或效果。尤其是，同一张卡如果先出现版本化消息、之后又混入未版本化消息，本轮没有定义其处理规则；不能把这个补丁当作已覆盖该场景。

进行完整 V2 对齐仍需要私有 V2 主规格、字段/schema、指标定义与版本/修订清单。拿到后，下一步先核对 `notice_version` 是否存在及其权威来源，再冻结同版本冲突、混流、版本缺口和取消后重开边界；不据本次合成结果宣称真实时钟或提醒效果得到解决。
