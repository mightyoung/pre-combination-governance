# 研究三 V2 对齐回合

本目录记录从 V2 公开规格 `cc6d59b88bda73381fc09d9091a224ab4155891e` 与治理实现 `214197c0370dfd60d23786884bb7ff785d8a0092` 得出的逐项状态矩阵、业务建议和一条已实际运行的合成开发场景。

- [ALIGNMENT.md](ALIGNMENT.md)：满足/不满足/未知矩阵、18 个通知字段、9 个确认字段、指标差距、证据限制与建议。
- [visualization/synthetic-event-timeline.html](visualization/synthetic-event-timeline.html)：单文件、离线可打开的中文时间线和卡片演变图。
- [visualization/synthetic-event-data.json](visualization/synthetic-event-data.json)：该次本地 ledger 运行的脱敏合成输入、状态快照、通知和关系历史。
- [visualization/generate_synthetic_timeline.py](visualization/generate_synthetic_timeline.py)：复现数据与图的脚本。
- [MAC_PERSISTENCE_MANIFEST.json](MAC_PERSISTENCE_MANIFEST.json)：本分支公开交付物的相对路径与校验值；Mac 根路径未指定。

重生成时间线：

```sh
python research-three/v2-alignment-20261011/visualization/generate_synthetic_timeline.py
```

该命令只调用纯软件 `AlertLedger`，不连接模型、投递服务、设备或运行器。所有 evidence refs 均为 `synthetic://` 占位引用，没有原始物理证据正文。记录中的 SIMULATED 不表示任何用户实际看到提醒。
