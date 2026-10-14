# 信息可辨识性：最小受控对照（预期手写，待独审）

保留无新增信息I1持续E1、I2隐藏独立e/E2，二者公开rows完全一致。三个新增臂仅在e加boundary_evidence：I3独立合格恢复ACTIVE→RECOVERED（time3.5）；I4合格作业台账W1结束/W2开始（closed3.25/open3.5），事件定义为作业实例而非“设备已安全”；I5独立状态源在3.5STOP、4RUN，跨样本物理阶段。三臂a-d E1、e E2，必首报1/5。五采样前缀风险均EXPOSURE，间隔恢复不等于SAFE。两臂baseline与前三valid臂前四输入相同，算法只从e收到信息后使用，不偷看未来。I6混合失效臂有过期恢复、BAD状态变化及两条合格台账W2/W3矛盾，物理e仍新E2，关系应UNKNOWN/待审，不能改真值抹去漏报。

所有四方法输入相同，使用同一公开证据有效性适配器；M0不是只看原窗口的弱对照，而是窗口＋同一附加证据。有效新增边界e独立分卡；失效附加证据e保留不确定待审；无证据M0原窗口行为/M1-3原不确定候选不变。共用适配器的规则依据是当前可见可靠时序，而非trace名/物理episode标签。不能把按本协议定义的合成正确率当方法优势或DS增益。

条件：同设备/任务绑定；源质量GOOD、资格QUALIFIED、独立血缘；known_time≤收到e的逻辑时刻；physical_time≤e.source_time；旧报警物理时间<新增边界时间，且物理及known时效≤2逻辑步。WORK_ROUND需明确之前实例关闭与不同新实例开放；SOURCE_TRANSITION需前STOP时刻晚于旧报警，后RUN不晚于新报警。不同合格证据互相矛盾则拒用，不能只取有利的一条。QUALIFIED是合成外部资格标记，本轮不校准可靠性或证明真实台账可信。

六有效性测试bundle：各三类型valid；未来/过期时序；BAD/非合格/非独立或重复血缘；合格轮次矛盾。只测纯公开证据gate，无assess调用。6＋120方法前缀＋102参考（30物理＋60DS＋12终点）＝228bundle，≤240。100%方法共享信息。DS内部资产组另报，不把bundle当底层调用数。

必first_alert只由new_event_first_alert判，不以risk_escalation/审阅抵扣。单列首报漏报、额外首报、拒判分母、首报逻辑延迟（非墙钟），并保留原物理提醒指标。方法终点手写参考是实现契约，物理oracle另评价错误；原true值/原三轮输出/代码不变。

本设计仅机制开发，信息介入由合成定义给出，有生成规则偏好风险；不能据此主张泛化/创新。需要独立标注与真实有效性依据另证。无网络/API/安装/付费，既有标准库runtime，wall120/CPU60、独立输出/一次消费/无重试；Terminal拒绝不绕过，准备后一个合并手动命令。

独审修正：恢复/独立STOP发生3.5，晚于前缀4采样time3、早于e/time4；oracle增加between_sample_motion，五采样状态RUN与间隔STOP不冲突。轮次有closed/open布尔及关闭3.25/开放3.5时间。两个矛盾台账source/acquisition分别ledger-Q/ledger-R，重复血缘另在gate测试覆盖；不将资格字段当真实可靠性验证。

首报验收口径：要求在每个必报prefix精确首报、无额外首报、逻辑延迟为0；missed_at_required_prefix/extra_at_nonrequired_prefix为精确prefix差集。窗口logical_delays仅作诊断，延迟命中仍未满足精确验收。首报验收与物理提醒验收分别写入收据，任一不满足均标NOT_SAFETY_ACCEPTANCE。
