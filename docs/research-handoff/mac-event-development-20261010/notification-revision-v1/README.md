# 提醒最小修订：独立静态版本

尚未运行，非作者两轮静态复审已收口；限定范围未发现新的确定阻断。保持原六轨迹代码/真值、18测试成功结果、旧profile和362冻结材料。新目录copy methods/reference/scorer/evaluator，变更worker的通知条件以及新2-case/40-slot评价尺寸；方法关联/风险/DS本身不变。原T3 oracle不修改，新N1按原T3标签、N2只增加e.danger_level HIGH，真值运行前按物理定义固定。

不确定新卡只有在此前同资产/同task/同target/同value存在GOOD且VALID报警，确认仍在2逻辑步有效期内、无当前/中间GOOD恢复证据时，作为possible_existing_event_update，保留uncertain:e/possible、association_established=false，不重复物理提醒。没有同context候选、有恢复或明确新卡时仍可发new_event_first_alert。HIGH新证据或新危险/冲突触发risk_escalation；风险降低/冲突消解仍写risk_state_update，不因降级单独再发升级提醒。所有card_updates为卡更新字段，不放notification_reasons，避免旧评分误当物理提醒。

边界：同资产/task候选不等于已确立关联；真实独立事件若公开字段与持续事件完全相同且无恢复/新危险线索，本代码不可辨认。必须保留不确定卡/更新待关联信息，不能声称防止全部漏报。此为开发诊断，不生产安全控制。M0也使用修订通知逻辑，准确名称为修订窗口方法；其窗口关联本身未改。

两个回归测试分别：N1新不确定卡不重复物理提醒且不合并；N2当前HIGH证据升级提醒且不强迫合并。每测试bundle调用整个2x5x4 run一次（40个assess），两测试80个assess＋主槽40个assess＝120实际方法调用；计费口径2测试bundle＋40主方法前缀bundle＋34参考bundle＝76，预算上限240，无重试。34参考含10物理前缀（每bundle4方法指标）＋20DS前缀＋4手写终点；DS内资产融合数另计，76不是底层调用次数。沿用原T3手写关联终点，因为HIGH差异不变事件分区。新程序尚无运行结果。

不调用原网络/fork/越界读写探针、旧监督器，不通过其他工具绕过Terminal拒绝。保留用户手动启动，CPU子50/父8、墙钟110主动止/名义120、9MiB阈值、一次消费、新输出、前后hash、失败日志/收据尽力；无OS级文件/网络隔离，限额/清理故障未验收，硬终止可能缺最终收据。RSS未测。用户已批准最小修复准备，此处不自行执行。

复审收口后用户手动命令：
```zsh
<LOCAL_RUNTIME_PATH> -I -B '<LOCAL_HOST_PATH>' --confirm-no-os-isolation --output-name manual-attempt-001
printf 'exit_code=%s\n' "$?"
```

输出目录属于notification-revision-v1，不是旧degraded-v1目录。失败不重试、不复用旧许可。MME-v2/D07仍不通过。新步骤不扩大数据/部署。

非作者首轮指出候选条件过宽，已收窄同目标/质量/值/有效期，并在首回归bundle内加不同设备/任务/目标、BAD质量、失效支持和恢复证据六个负对照。仍无法辨别公开字段完全相同的新独立物理事件；这种情况必须显示review_required待关联，不能声称首报全覆盖。后续需要独立事件证据，当前不增加输入字段或生产部署。
