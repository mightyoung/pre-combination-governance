# 生命周期预算明确批准后的交接（2026-10-21）

当前基线为原独立分支 `task/research-three-config-provenance-20261021` 的 `8784a95f06257448bec365c53143c8d4f6761d79`。本轮开始时工作树干净，`git ls-remote --heads origin task/research-three-config-provenance-20261021` 确认远端同 SHA。继续既有 AGENTS/PLAN/任务目标，不更改方法、样本、oracle、runner 时间策略或身份策略。

## 明确批准与配置

父线程 `01a156fa-2aa1-7484-9e3f-661da0bc00ce` 提供可信用户历史：助手问“时间上限是否按原建议，设为整个生命周期总计600秒（含9秒清理）？另外两项研究继续推进，不等这个答复。”，用户回复“可以”。本轮授权只落实配置、测试、预检、独立审查与原分支提交推送，不授权正式实验、权限提升或安全/网络配置变更。

`RESOURCE_APPROVAL_20261021.json` 记录上述完整问答及 `wall_scope_resolution`；`initial_approval_snapshot` 保存此前每槽范围的原始歧义，当前顶层描述改为明确生命周期范围。此批准解决 wall 映射，不追溯改写历史预检。

`TASK_MANIFEST.json` 当前资源为：

| 字段 | 已批准值/范围 |
|---|---|
| `wall_seconds` | 600，整个 sandbox 生命周期（Docker 设置前至清理后），含现有 9 秒清理保留，不是每槽 |
| `memory_bytes` | 268435456，per-container cap |
| `pids_limit` | 16，per-container cap |
| `max_method_output_bytes` | 9437184，所有槽累计 stdout/stderr |
| `cpu_quota_millis` | 原值 1000，串行单 CPU |

`resource_profile_status=PRE_REGISTERED` 仅表示资源配置完整登记，不表示 runner/task READY、Docker 资格通过或正式实验获准。代码/schema/25 项执行 pin 未改变，TASK 及交付文档/测试的持久化 hash 已重绑。

## 实际检查与终态

从 `package-v1` 运行：

| 命令 | 终态/证据 |
|---|---|
| `python3 -I -B -m unittest discover -s tests -v`（配置变更前，先更新断言） | exit 1，60 tests、3 failures：profile仍缺wall、批准仍每槽、预检仍资源阻断；`LIFECYCLE_APPROVAL_TEST_RED_20261021.log` |
| `python3 -I -B -m unittest discover -s tests -p test_package_contract.py -v`（顶层批准原文更新前） | exit 1，5 tests、1 failure：仍为此前泛化批准句；`LIFECYCLE_APPROVAL_PROVENANCE_RED_20261021.log` |
| `python3 -I -B -m unittest discover -s tests -v`（落实后） | exit 0，60/60 PASS；`LIFECYCLE_APPROVAL_TEST_GREEN_20261021.log` |
| `python3 -I -B runner.py --task-manifest TASK_MANIFEST.json --preflight-only` | exit 20，BLOCKED，`missing_resource_fields=[]`；资源与pin检查后阻断于身份，详 `LIFECYCLE_APPROVAL_PREFLIGHT_20261021.json` |
| `git diff --check` | exit 0，无 whitespace error |

测试保留 wall≤9 拒绝、bool/非整数/非正数资源拒绝和 CPU=1000 约束。包入口测试显式 mock 不匹配身份，并断言 DockerSession 未调用，因此完整配置不会令软件测试意外运行资格容器。其余 simulated/fake 研究输出只供合同测试，不能计作正式槽、AI预标注或人工真值。

实际预检记录 `HOST_IDENTITY_MISMATCH: required 65534:65534, got 1000:1000`，`task_status=BLOCKED`，qualification `NOT_VERIFIED`。容器/网络/资源/OOM资格项均 `NOT_RUN`；host canary baseline 的 FAIL 来自身份检查，未读取 canary。`method_start_requests=0`、`method_invocations_started=0`、`completed_method_invocations=0`，`research_acceptance=NOT_EVALUATED`。未使用任何提升权限、身份切换、Docker启动、镜像构建/拉取、凭据设置或网络配置动作。

## 剩余明确缺口

- **身份（观察到的门禁阻塞，非审批拒绝）**：目标是当前执行环境；当前身份1000:1000不满足原资格策略65534:65534。下一步需提供符合既有策略的已授权执行上下文，不能通过改门禁或提升权限绕过。当前上下文不得宣称隔离/OOM/实际资源限额已获资格。
- **私有 V2 来源链（材料未提供）**：本轮复核公开 `research-three/v2-alignment-20261011/README.md`，仍固定公开规格 `cc6d59b88bda73381fc09d9091a224ab4155891e` 并明确原始 Mac V2 未纳入。本轮没有收到主规格、字段/schema、指标定义和版本/修订清单，无法核验公开版之外的私有原始规则。未访问私有数据/服务或猜测内容；公开软件测试不以私有材料作笼统前置。
- **正式运行许可未授予**：完整资源批准不等于80槽许可。资格容器、80正式槽、冻结研究方法、模型/真实数据、旧失败重跑均未执行。旧1,464整体 FAILED 与 NOT_DELIVERED 保留；本轮不产生研究效果或真值结论。

## 独立审查与交付

独立 reviewer 只读审查配置、批准问答/范围与测试，独立 isolated suite 60/60 PASS（exit0，0.773秒）。确认入口测试不会因完整资源而意外调用Docker，正式授权仍false；指出当前文档/预检证据及持久化清单应更新，本次已更新，旧范围待决材料已标历史。

完整提交 SHA、远端链接和最终 closure 复核在交付消息提供，避免提交自身循环引用。本轮没有自动审批拒绝或结果不明的操作。
