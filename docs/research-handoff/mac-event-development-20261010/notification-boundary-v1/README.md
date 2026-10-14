# 边界小试合并执行（静态准备，等待用户手动运行）

独立手写预期审核已完成，代码最终静态复审已收口，限定范围未发现新的确定执行阻断；未运行。5测试bundle＋100主槽＋85参考bundle＝190，≤240；测试内6 assess＋主100＝106实际assess，DS内部资产组另报。参考25物理前缀＋50DS前缀＋10手写方法终点；物理真值与方法契约参考分开，不能用方法生成物理真值。

用例包括B1不同设备/任务的新独立事件首次提醒、B2 GOOD恢复后复发、B3 HIGH降级后再升级、B4/B5公开字段完全一致但物理事件不同。新增字段review_notification_reasons使M1/M2/M3的不确定卡产生明确审阅提醒；它不抵扣物理must_notify。本组预计暴露B5物理首报缺口，不能用“待审”冒充首报覆盖。M0没有关联不确定卡的机制，会保留自身误并/误拆/冗余提醒，单独报告。

输出判读：exit0只表示诊断计算、回归和参考一致性完成；如物理提醒存在漏报或额外提醒，receipt会标DIAGNOSTIC_COMPLETED_WITH_PHYSICAL_ALERT_GAPS_NOT_SAFETY_ACCEPTANCE，并列physical_misses，禁止宣传整体物理提醒通过。即使5测试通过，第5个是不可区分性诊断，不是安全通过。

同runtime标准库、无新增依赖/网络/API/付费/凭证，不运行旧网络/fork/越界探针。文件输入/hash是约定及检测，没有OS文件/网络隔离。子CPU硬50/父8、墙钟110主动止/名义120、输出9MiB，一次消费、独立输出、失败停止不重试；资源故障/极限/清理未验收，RSS未测，硬终止可能缺最终receipt。严格遵守平台工具沙箱和Terminal拒绝，不通过exec/其他终端绕过，仅用户手动一条合并命令。

```zsh
<LOCAL_RUNTIME_PATH> -I -B '<LOCAL_HOST_PATH>' --confirm-no-os-isolation --output-name manual-attempt-001
printf 'exit_code=%s\n' "$?"
```

回报打印的receipt路径及退出码，随后只读审阅全部明细；不要重复命令。原两次成功结果/原代码真值/profile/旧362文件保留，MME-v2未找到、D07未执行仍独立报告，不生产部署或声明论文创新。
