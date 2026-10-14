# 研究三：当前可复现实验材料总入口

截至notification-boundary-v1手动attempt001，三轮降级开发小试均保留独立代码/公开合成输入/物理oracle/预算与参考/绑定清单/原始日志/退出及资源收据/只读审计。固定runtime为<LOCAL_RUNTIME_PATH> a21866022ba9ec08a1a5edf4a321718d633a2ab1，旧BUILD005-r2 362文件MANIFEST SHA a24c9906645e3c5969d0ba7260bfbdde0644f71686d6a2023cfd1ef4b2bb2559均保持。

|轮次|输入/方法|测试＋主槽＋参考|实际结果|
|---|---|---|---|
|[初始降级](degraded-v1/README.md)|6轨迹×5×4|18＋120＋102＝240|运行/参考通过；原T3有重复提醒|
|[提醒修订](notification-revision-v1/README.md)|2轨迹×5×4|2＋40＋34＝76|N1重复物理提醒消除，N2 HIGH提醒保留；新事件/降级未在该轮覆盖|
|[边界诊断](notification-boundary-v1/README.md)|5轨迹×5×4|5＋100＋85＝190|B1/B2/B3指定提醒符合；B5四方法漏物理首报，整体physical acceptance=false|

三轮总计506声明计算bundle，分别授权且各≤240；不是单轮突破预算，亦非底层调用总数或三轮统一统计样本。当前边界轮5测试内6assess＋主100＝106实际assess，参考内部资产组另报。各测试通过只说明其明确断言，包含已知限制诊断，不能把通过率当安全有效率。

## 读取与核验路径

- 初始：[收据](degraded-v1/manual-attempt-001/receipt.json)、[只读报告](degraded-v1/manual-attempt-001-readonly-audit/report.md)、[计数更正](degraded-v1/manual-attempt-001-readonly-audit/count-correction.json)。
- 修订：[收据](notification-revision-v1/manual-attempt-001/receipt.json)、[报告](notification-revision-v1/manual-attempt-001-readonly-audit/report.md)、[全部通知](notification-revision-v1/manual-attempt-001-readonly-audit/all-notification-details.csv)。
- 当前：[手写用例](notification-boundary-v1/case-plan.md)、[公开输入](notification-boundary-v1/public-input.json)、[物理oracle](notification-boundary-v1/oracle.physical.json)、[手写方法终点](notification-boundary-v1/terminal-reference.json)、[绑定清单](notification-boundary-v1/binding.json)、[源码](notification-boundary-v1/worker.py)、[5回归](notification-boundary-v1/regression_tests.py)。
- 当前结果：[收据](notification-boundary-v1/manual-attempt-001/receipt.json)、[stdout](notification-boundary-v1/manual-attempt-001/stdout.log)、[stderr](notification-boundary-v1/manual-attempt-001/stderr.log)、[审计JSON](notification-boundary-v1/manual-attempt-001-readonly-audit/audit.json)、[全部通知](notification-boundary-v1/manual-attempt-001-readonly-audit/all-notifications.csv)、[报告](notification-boundary-v1/manual-attempt-001-readonly-audit/report.md)、[实际结果非作者复核](notification-boundary-v1/manual-attempt-001-readonly-audit/non-author-result-review.md)。

binding列固定文件SHA，receipt列日志SHA，intent绑定binding SHA，审计再核完整性/槽ID/公开报警卡/原冻结数据。预期在执行前手写并经非作者复审，不调用被测逻辑生成物理真值；手写方法终点只检实现一致性，另由物理oracle评价错误。

## 历史命令与复现约束

各版本README保留真实手动命令：现有Python -I -B，对该版本launcher.py，--confirm-no-os-isolation --output-name manual-attempt-001。这三次许可消费标记execution-used.json已消耗；命令是历史记录，不能再执行或删除标记“复现”。现有结果可只读核验。新独立重复实验须另建经审核、重新绑定的新副本与一次授权，保留当前输入/真值/结果；本轮未准备新重复实验，发现解释前不自动加下一轮。

平台工具沙箱及CUA Terminal拒绝不关闭/不绕过，三轮均用户手动原生Terminal执行。无实验OS文件/网络隔离、无新依赖/下载/API/费用/代理改动/远端发布。单子CPU50/父8、wall110主动/名义120和输出阈值是本协议措施；未做极限/故障/清理资格，RSS未测、硬终止回执尽力。计时截至收据写前，不完整计最终写入。

## 当前结论边界

B1公开独立设备/任务、新事件首报不被压掉；B2明确GOOD恢复后复发；B3降级状态与再HIGH提醒均在这组实测符合。M0恢复前后错误合并仍在，提醒命中不等于关联正确。B4/B5公开输入及各方法全部结果完全相同，B5真实独立e物理首报四方法漏掉；M1-3审阅提醒不抵扣，窗口还额外提醒。物理首报权衡不能改真值掩盖。

此为合成开发诊断/工程修复与可观察性示例，不是现场泛化、事故概率校准、论文创新或DS业务收益证据。MME-v2原始预注册仍未找到、D07未执行，正式研究仍受阻。本轮未新增下一轮或生产部署。
