# 可辨识性与首报机制：CPU 配对诊断任务草案

- **Task ID:** `PCG-IDENTIFIABILITY-PAIRED-CPU-001`
- **Status:** `DOCUMENT_ONLY; PLANNED_NOT_RUN`
- **Evidence class:** 对已保存合成结果的只读诊断，以及未来一次小型、来源可核验的 CPU 复核计划。不是新实验结果、正式效果结论或安全验收。

## 来源与只读核验

- 结果材料来自 `task/research-handoff-v1` 的 `ed463fa208d3fcadf5c8cb1e0c4505f64d4e7ca2` 与 `910302bac55487a542c656288d8202bd950e1b56`。两提交依次新增 99 与 16 个文件，共 115 个；本计划不修改该分支上的文件。
- `mac-identifiability-result-20261014/publication-manifest.json` 声明 15 个结果文件。本次从提交对象读取公开文件逐项核对，15/15 字节数与公开 SHA-256 匹配。未读取私有 Mac 路径或原始日志，也未执行随附 launcher、method、scorer 或 evaluator。
- 保存结果记录 6 个 gate bundles、120 个 method-prefix slots、102 个 reference bundles，共 228 个 bundles；直接 method assess 次数为 120。它们不是 228 个独立样本。保存的 6 个 gate tests 和 72 个 reference assertions 是实现契约检查，不能抵销首报或物理 oracle 失败。
- 保存收据有一次 attempt、child exit 0、error 为 null、CPU 0.542084 秒、写收据前 wall 0.857483 秒。执行来源确认仍为 `PENDING`，terminal top-level exit 未独立确认；这些时间不是完整墙钟或通知延迟证明。原执行不重跑，旧收据和失败状态保留。

## 诊断

### I1/I2 是信息不可辨识，不是可由算法猜出的分类

对保存的公开 `public-input.json` 只读比较得到：`I1_NO_INFO_CONTINUING` 与 `I2_NO_INFO_NEW` 的五行 method-visible 输入完全相同。`actual-output/main.json` 中两臂各 20 个 method/prefix 输出也逐项相同。两者差别只存在于 physical oracle：I1 要求继续事件，I2 是隐藏的新事件。

因此，在没有新观测时，确定性方法不可能既满足 I1 的“prefix 5 不报新事件”，又满足 I2 的“prefix 5 必须首报”。随机猜测只会在漏报与误报之间分配错误，不能恢复缺失的信息。保留 `possible` / `UNKNOWN_REVIEW` 是合理的身份不确定输出；它不能被计作 I2 的必需首报。保存结果中 I2 的四方法均漏 prefix 5，符合这条可辨识性边界，不单独证明四种方法都存在算法缺陷。

可增加的信息必须在决策 cutoff 前可见、绑定到同一 asset/task、来源独立且具备可核验的质量/资格/时间谱系。已有合成臂展示了三种候选信号：有效 `RECOVERY`（ACTIVE→RECOVERED）、显式关闭/开启的 `WORK_ROUND`、独立 `SOURCE_TRANSITION`（STOP→RUN）；I3–I5 在这些合成资格假设下于 prefix 5 首报。它们证明的是给定合成 gate 的行为，不证明真实来源可靠。`WORK_ROUND` 还把实体语义改成作业实例，不能自动当成物理事件或 SAFE。

### M0 的 prefix 3 额外首报是独立的规则/口径问题

保存 CSV 的 24 条 trace-method 行共计 8 个必报 prefix 5 漏报，以及 6 个非必报 prefix 3 额外首报；6 个额外首报全部来自 M0。I2/I6 的 M0 记录同时包含 prefix 3 额外首报和 prefix 5 漏报，两者不能相互抵销。

只读检查保存的 M0 prefix 3 输出：`cards` 把 a、b 放到 `window:a`，把 c 新开为 `window:c`；通知原因包含 `new_event_first_alert`，而 `card_updates` 为空、`risk_state_update` 为空。保存的 `methods.py` 显示 M0 的 `window_cards()` 仅按 asset 和到达窗口分组；prefix 3 的 c 首次出现在 asset B。M1–M3 则用 `task`/`epoch` 规则分组，且 M2/M3 的 D-S motion fusion 是附加诊断。因此 M0 的额外首报来自 asset-scoped window 把跨资产同 task 记录开成新卡，不是 D-S 的收益或损失。

按本结果的 physical-event oracle，这属于方法/事件分组与验收契约不一致；若 M0 本来就被定义为 asset-local baseline，它是预期的基线行为而非实现 bug。改变 M0 的分组键会改变基线，不能在分析中悄悄修正。当前计划保持 M0 原样，单独记录该额外首报。

两项保存验收均为 false：`first_alert_acceptance=false`、`physical_notification_acceptance=false`。后者是基于保存 oracle 的报警条件验收，不代表用户实际投递；没有真实送达证据。拒判仍在分母中，missed 的逻辑延迟是 null，不得写成 0。

MME preregistration v2 未定位，D07 未执行；本材料不能作为论文确认性研究或正式主假设的依据。

## 下一轮最小配对诊断设计

本节是未来任务草案，不授权或启动运行。目标是用一份可验证的 CPU 回传包复核“无额外信息时不可辨识；增加一个有效边界观测后才可能区分”，并把 M0 的额外首报单独保留。不得把结果包装为独立样本优势或生产性能。

### 固定输入与配对条件

基线固定为公开提交 `910302bac55487a542c656288d8202bd950e1b56` 中的：

- `public-input.json`：17,222 bytes，SHA-256 `905d0670f9693217ef4713f39378c29a07e5213f1c43abf2f527d55f31cd1de9`。
- `oracle.physical.json`：5,646 bytes，SHA-256 `f41cddf14c1905b5358280445efbd542685fa1e2cfb61d6dc78274ec42fda902`；仅 scorer 可读。
- 方法/gate 源码快照：`ed463fa208d3fcadf5c8cb1e0c4505f64d4e7ca2` 的 `identifiability-v1-PREPARED-NOT-RUN` 文件与 binding。任何代码或参数变更须生成新版本和新 SHA，不得覆盖原绑定。

执行时为每个输入生成不含 I1/I2/I3 标签、physical episode、真值或 oracle 引用的 opaque case ID。方法进程每次只收到当前 prefix，不收到后续行或完整 trace。四种原方法 M0–M3 原样冻结；M0 在 prefix 3 的新卡和首报必须照实保留。

| Case | 方法可见输入 | scorer-only oracle | 配对用途 |
|---|---|---|---|
| A | I1 的五行原样、无 boundary | continuation | 与 B 构成无额外信息对照 |
| B | 与 A 字节相同的五行、无 boundary | hidden new event | 检验不可辨识；A/B 标签不得传给方法 |
| C | B 的五行，只在 e 添加一条有效独立 RECOVERY：ACTIVE→RECOVERED；`previous_time=2`、`physical_time=3.5`、`known_time=3.5`，quality GOOD、reliability QUALIFIED、独立且 acquisition 唯一 | new event | 唯一正向信息干预；其他输入固定 |
| D | B 的五行，只添加一条与 C 同形但时间无效的 RECOVERY（例如 `previous_time=0`、`physical_time=1`、`known_time=4`，早于旧报警） | new event | 负对照；gate 应拒绝，保留 UNKNOWN_REVIEW，不伪装成确认 |

A/B 应保持公开输入及输出一致；不允许按 oracle 标签分别调参或修改定义。C 的资格、独立性与时间均只是合成记录属性。D 的拒绝不算成功首报；其 physical-oracle 漏报照样记失败。新增 boundary 只在它的 known time 到达后进入方法输入，不能回填历史 prefix。

计划主输出为 4 cases × 5 prefixes × 4 方法 = 80 个 method-prefix slots。pair、prefix、reference 计数须分别报告，不得称为 80 个独立样本。对首报要求严格按 exact required prefix、无额外 first alert、0 逻辑 prefix delay 评分；review、risk escalation、handling follow-up 不抵扣首报。physical-oracle alert acceptance 与 first-alert acceptance 分列。实际用户投递仍标记 `NOT_DELIVERED`。

### Oracle 盲隔离与回传边界

1. 运行前固定公开输入、方法、gate、runner、schema、参数和 oracle sidecar 的 SHA-256；单独冻结 opaque method-input manifest。方法容器/进程不得挂载 oracle 文件，也不得导入 scorer。
2. 每个 prefix 的方法输出及其完整 card/action/review 字段先写入新 bundle、规范化并哈希；只有输出哈希冻结后，独立 scorer 才能读 oracle sidecar。输出不得含 case truth、trace 名或隐藏未来字段。
3. 需要 OS 级文件/网络隔离、单 CPU、进程树限制和可记录的内存上限。上一收据的来源与 terminal exit 未确认，且 RSS/资源故障资格未知；不得把其资源文字当作已验证限额。新任务 manifest 必须在运行前逐项冻结 CPU、wall、memory、output 上限及其 OS 强制/测量方式；任一缺失即 BLOCKED。
4. 每个 run ID 只允许一次 attempt。预先定义的研究结果失败（首报漏报/额外报告、边界拒绝/接受不符）不提前终止剩余安全槽位；保留逐槽输出并交完整 bundle 给 scorer。资源超限、非零退出、hash/pin 不匹配、隔离丢失或 oracle 泄漏属于协议/执行故障，立即停止并保留已完成槽位、部分产物和原因；不得不安全地继续，也不得同 ID 重试、改写输入、改 oracle 或调整首报口径使结果变绿。

### CPU 命令与状态字段

现有 `615bfd…` 分支中的 `user_cpu_replay_runner.py` 是两跳 lineage 任务，不是本 identifiability runner。公开的 Mac `launcher.py` 路径经过脱敏，带 internal parent gate；`offline_evaluator.py` 的直接入口明确为 `STATIC ONLY`。因此目前没有可安全复制到计算服务器的本任务命令。以下仅是将来 runner/validator 包必须实现的命令接口，**不是当前可执行命令**；须先由独立发布提交创建脚本、冻结其 manifest，并完成隔离审查：

```sh
python3 -I ./run_identifiability_pair_v1.py \
  --task-manifest ./PAIR_TASK_MANIFEST.json \
  --run-id <unique-run-id> \
  --output-dir ./runs/<unique-run-id>

python3 -I ./validate_identifiability_pair_v1.py \
  --bundle ./runs/<unique-run-id>
```

回传至少包含：`task_id`、`run_id`、`task_status`（execution/bundle 的 PASS/FAIL/BLOCKED）、`research_acceptance`（TRUE/FALSE/NOT_EVALUATED）、源 commit 与代码/input/oracle/schema SHA、完整命令、实际 interpreter/python/platform、started/finished UTC、attempt 数、`planned_method_invocations=80`、`completed_method_invocations`（实数，0–80）、`partial`、`stop_reason`、child exit 与 terminal top-level exit、CPU/wall、memory cap/peak RSS（不可得则写 UNKNOWN）、stdout/stderr 和每个 artifact 的 bytes/SHA。两个状态字段相互独立：仅当所有预定槽位完成且 bundle/协议完整性通过时 `task_status=PASS`；只有完整 bundle 经 oracle 解封和 scorer 评估后才填写研究接受 TRUE/FALSE。若因协议/执行故障中断，填 FAIL 或 BLOCKED、`research_acceptance=NOT_EVALUATED`，并报告实际完成数、部分状态和原因。研究接受 FALSE 本身不使已完整执行且完整封存的 bundle 变成 execution FAIL。

机器结果须含所有已完成槽位的逐 case/method/prefix 输入/输出 hash、cards、notification reasons、first-alert prefix、accepted/rejected boundary reasons、possible/review 状态；仅在完整且哈希封存的 bundle 上解封 oracle 并评分，另给 `required_first_alert_prefixes`、`actual_first_alert_prefixes`、missed、extra、logical delay（漏报为 null）、两类 acceptance、rejection denominator、`production_truth_denominator=0`、`production_accuracy=NOT_COMPUTABLE`。完整运行预期 `planned_method_invocations=80`；回传的 `completed_method_invocations` 必须是实际值，不能把计划数写成完成数。`task_status=PASS` 只表示全部预定槽位执行完且 bundle/协议完整，不得覆盖 `research_acceptance=false` 或“非安全验收”。

### 停止条件与待用户决定

- 源码或输入 manifest 不匹配、执行来源/terminal exit 无法确认、OS 级隔离/资源上限缺失、方法可访问 oracle/trace 标签/未来 prefix：运行前 BLOCKED。
- A/B 输入不再完全相同或方法输出受 case 标签影响：协议/隔离完整性失败，立即停止，不调参；保留实际完成槽位与部分产物。
- C 的 boundary 未通过预先冻结的 gate，或 D 的 stale boundary 被接受：记为研究结果失败，继续其余预定槽位；完成并哈希封存全部安全槽位后交 scorer，最终 `research_acceptance=false`。
- 任意首报漏报或额外 prefix 3 报告：记为研究结果失败并继续其余预定槽位；完整运行后由 scorer 汇总。非零 exit、资源超限、隔离丢失、缺少原始日志/哈希或完整性校验失败属于协议/执行故障，立即停止，保留实际完成数、部分产物和明确原因，置 `task_status=FAIL/BLOCKED`、`research_acceptance=NOT_EVALUATED`；不重试同 ID。

当前不建议改变主研究假设；这份计划只测信息边界和实现行为，不检验 D-S 优越性。若要把目标从“准确的新事件首报”改为“身份未定时先发预警”，须用户先决定预警是否独立于事件确认、如何记入 false-positive/及时性指标。若采用 WORK_ROUND 作为主要区分证据，须用户先决定事件单位是否改为作业实例。若要把 M0 改成 task-aware 分组，须用户先批准新的方法版本/基线；本计划不做该改动。

## 不在本任务范围

- 不运行 228-bundle 原命令、任何新合成方法调用或正式实验；不改写 8 个旧漏报、6 个 M0 额外首报或两项 false acceptance。
- 不接触私有 Mac、外部服务器、外部数据、模型、GPU、网络服务、安装、真实通知或执行器资格探测。
- 不把 child exit 0 当作完整命令成功，不把本地逻辑时延当墙钟延迟，也不把实现 reference match 当 physical truth。
