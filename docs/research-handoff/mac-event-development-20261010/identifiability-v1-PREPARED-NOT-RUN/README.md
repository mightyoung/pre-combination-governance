# 信息可辨识性对照：合并手动运行

独立新版本，未运行，最终非作者静态审核通过。6gate测试bundle＋120主方法前缀＋102参考（30物理前缀＋60DS＋12手写终点）＝228≤240。gate测试无assess，主120assess，DS内部资产组另报；bundle不是底层调用数。四方法收到相同附加信息并共用相同证据gate，不能把合成定义/共享规则带来的改善当本方法或DS优势。

I1/I2保持相同无新增信息的持续/隐藏新事件对照；I3只加明确恢复；I4只加台账旧轮次关闭/新轮次开放；I5只加独立源STOP→RUN；I6有过期/BAD/矛盾信息，仍保留新物理事件真值、UNKNOWN_REVIEW及审阅。所有有效性字段均公开合成外部假设，不证明真实源可信。RECOVERY/STOP发生3.5，处于prefix4采样3与prefix5采样4之间；I4 closes3.25/opens3.5，避免把五采样RUN与间隔恢复混淆。信息只在e到达后可用，不泄露未来。

指标分别记录：仅new_event_first_alert计首次提醒，risk_escalation/审阅不能抵扣；首次漏报/多报/逻辑前缀延迟、关联拒判分母、原物理提醒和DS参考一致。物理oracle是手写事件真值，终点参考是手写方法契约；两者分开，不能按被测输出反填。预期无信息隐藏新事件及失效信息仍可能漏首报，退出0代表计算/一致性完成，非安全验收；收据列物理gap并附first_alert_checks。

保持原三轮代码/真值/原结果/profile/362文件冻结。仅现有标准库runtime，不网络/API/安装/下载/付费。无OS文件/网络隔离、固定hash不是写保护；CPU子50父8/名义60、wall110协作/名义120、9MiB输出、一次消费独立目录失败即停无重试；RSS、极限/故障/清理资格未验证、硬终止回执尽力。严格遵守平台/Terminal拒绝，不通过exec/替代终端代跑。

用户一个合并命令：
```zsh
<LOCAL_RUNTIME_PATH> -I -B '<LOCAL_HOST_PATH>' --confirm-no-os-isolation --output-name manual-attempt-001
printf 'exit_code=%s\n' "$?"
```

不要重复命令；回报打印的receipt路径/退出码，再只读核验每臂首报/多报/拒判/延迟及失败。正式MME-v2/D07、OS隔离、安全控制部署和论文创新均不由此通过。
