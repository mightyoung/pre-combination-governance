# 批准落实与范围核对（2026-10-21）

> 历史检查点（8784a95）。wall 范围待决已由后续明确批准解除；当前状态见 [生命周期批准交接](LIFECYCLE_APPROVAL_HANDOFF_20261021.md)。本报告中的 null/pending 和旧预检只描述该历史检查点。

本轮从已推送的 `38ce038cfc384efd51d62ee250cfbe6f2eac005e` 继续；同一独立分支 `task/research-three-config-provenance-20261021`，工作树起始干净，远端 head 已核对。沿用已读 AGENTS、原任务目标与配对 PLAN，不改方法/输入/真值/历史研究结果。

## 批准来源及已落地部分

用户通过父任务提供的可信历史明确说：“均批准按照建议执行，并行执行三个研究任务的下一步吧”。本轮父任务据此授权资源配置、独立软件测试/审查、原分支提交推送，明确不授权正式 80 槽实验，也不允许提升权限、修改安全/网络、配置凭据或购买。原文与父线程标识、具体四值、作用范围、限制保存在 `RESOURCE_APPROVAL_20261021.json`，它是批准来源记录，不是执行结果。

`TASK_MANIFEST.json` 已应用无歧义的三项：`memory_bytes=268435456`、`pids_limit=16`、`max_method_output_bytes=9437184`（所有槽累计 stdout/stderr）。CPU 保持 1000，即串行单 CPU。测试/报告和 manifest 的持久化 hash 一并更新。

**wall 存在具体范围冲突，尚未转换。** 本轮父任务及其引用助手消息写“每槽 600 秒”；原决策报告 `REPORT_EXECUTION_PINS_20261021.md`、`WALL_TIME_SCOPE_REVISION_20261014.md`、当前 schema 与 runner 都把 `wall_seconds` 定义为完整 sandbox 生命周期：Docker 设置前至镜像清理后，包含资格步骤与所有槽，并预留 9 秒清理。不能把批准的每槽上限当作完整生命周期预算，也不能自行乘以 80 得到 48,000 秒。批准记录保存 `approved_values.wall_seconds=600`、`approved_wall_scope=per_slot`，标记 `PENDING_SCOPE_RESOLUTION`；TASK 中 wall 仍 null、status 仍 `BLOCKED_MISSING_VALUES`。

这是范围映射待决，不撤销任何数值批准；三个已明确的字段已落实。没有擅自更改 runner 时间策略、放宽上限、批准身份变更或正式实验。

## 实际软件检查

从 `package-v1` 运行：

| 命令 | 实际终态 | 保存证据 |
|---|---|---|
| `python3 -I -B -m unittest discover -s tests -v`（配置变更前，新增断言后） | exit 1，60 tests、2 failures：三项值未落实及批准来源文件缺失 | `RESOURCE_APPROVAL_TEST_RED_20261021.log` |
| 同命令（落实配置/记录后） | exit 0，60/60 PASS | `RESOURCE_APPROVAL_TEST_GREEN_20261021.log` |
| `python3 -I -B runner.py --task-manifest TASK_MANIFEST.json --preflight-only` | exit 20，BLOCKED；missing 仅 wall；0 starts / 0 completed | `RESOURCE_APPROVAL_PREFLIGHT_20261021.json` |
| 纯 Python 调用 `_qualification_identity_failure_evidence(manifest['resources'])`，读取 getuid/getgid 与已保存的公开来源文档/hash | exit 0，身份 NOT_VERIFIED，全部容器检查 NOT_RUN | `RESOURCE_APPROVAL_IDENTITY_SOURCE_AUDIT_20261021.json` |

测试新增数值边界：各资源的 bool、0、负数、float、string 均拒绝；wall ≤9 秒拒绝；CPU quota 非 1000 拒绝。完整资源字典的 READY 仅是 synthetic 值校验，不是研究方法执行、隔离资格、人工真值或正式实验许可。旧资源缺失测试仍使用显式缺失 fixture 验证 fail closed。

首次 red 尝试曾因批准文件未创建而产生 FileNotFoundError；在实现配置前，把它改成明确的“批准来源文件缺失”断言，再取得保存的 2 failures 红灯。没有以导入/文件错误冒充正确功能失败。日志只归一化本机 package 路径与行尾空格。

## 现有能力内的阻塞与明确下一步

1. **wall 范围待决（pending）**：目标是 TASK 的生命周期 wall 字段；批准证据是每槽 600 秒，现有字段是全生命周期。最小决定为“确认 600 秒也用于现有完整生命周期”，可直接填 600；若确实要求每槽 600 秒，则需另定完整生命周期上限及审查新的 per-slot deadline 实现。任一路径均不自动授权正式运行。
2. **执行身份不合格（观察结果，不是审批拒绝）**：当前 UID:GID=1000:1000，原 runner 要求 65534:65534，`HOST_IDENTITY_MISMATCH`。没有 sudo、setuid、切换用户、改门禁或启动容器。后续须提供符合既有身份策略的已授权上下文；当前不能宣称 Docker 资格已通过。
3. **私有 V2 来源链缺失（available materials 未提供）**：README 固定公开规格 commit `cc6d59b88bda73381fc09d9091a224ab4155891e`，明确私有 Mac V2 未纳入；ALIGNMENT 明确公开确定性工作不要求私有原文。未发现新提供的私有主规格、字段/schema、指标定义和版本/修订清单，不能建立私有规则权威链。只搜索/读取当前项目公开文件，未扫描凭据、访问 Mac 或私有服务。缺少私有材料仅阻断超出公开版的核验，不阻断本轮公开配置与测试。
4. **正式执行许可未授予**：未运行 80 槽、资格容器、OOM 探针、模型/真实数据/AI 预标注/人工标注。正式 method invocations=0，research acceptance=NOT_EVALUATED。旧 1,464 整体 FAILED、NOT_DELIVERED 记录及此前所有失败原样保留。

本轮没有自动审批拒绝或结果不明的写操作。所有未执行项是授权边界/已有门禁阻塞，不会以派发、开发 PASS 或资源批准替代研究执行证据。

## 独立复审

独立 reviewer 只读复审配置、批准来源和范围处理，并独立运行 isolated 软件测试：60/60 PASS，exit 0（0.780 秒）。确认三项已应用、wall 范围冲突明确保留，未扩大执行预算；未启动容器/研究方法或修改权限。复审指出持久化清单需重绑、README 旧状态应改为历史描述，交付前均落实。最终 closure 核验、完整提交 SHA 与可访问链接在本轮交付消息提供，避免自身引用。
