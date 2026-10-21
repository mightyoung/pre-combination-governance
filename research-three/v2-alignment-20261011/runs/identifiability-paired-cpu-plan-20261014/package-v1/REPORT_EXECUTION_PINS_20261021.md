# 执行 pin 完整性增量与云环境只读核查（2026-10-21）

## 结论与研究边界

本次交付修复 manifest 可删除非核心执行文件 hash 的失败关闭缺口。原入口仅强制要求 methods/shared_context/worker 三项 hash；现在要求本包已发布的完整 25 项执行文件集合，缺少任一项或加入额外路径均在读取运行输入、创建输出和请求 Docker 前被拒绝。包括 slot_worker、runner、来源绑定、来源准备状态等文件。保留原有逐文件 SHA 校验及三项固定方法源码值。

这是软件配置/来源文件清单完整性修复，不证明 source-binding 内声明来自权威源，也不认证私有 V2。它依赖受审查的 runner 和 manifest 一起交付；不能防止攻击者重写两者。JSON Schema 仍是宽松的文件 hash 字典形状，精确集合由运行时门禁执行。

开发 synthetic 合同检查与正式实验分开：本次正式 method invocations=0，80 槽未运行，未调用冻结研究方法、模型、外部数据、AI 预标注或人工标注。production truth denominator 未新增。旧 1,464 检查整体 **FAILED**、投递 **NOT_DELIVERED** 原样保留（见本目录上三级 `RESULT_DRIVEN_ALERT_EVALUATION_REVISION_20261014.md`）。

## 基线、任务与冲突检查

- 只在用户提供的保存云环境 `/workspace/pre-combination-governance` 工作。
- 初始 `work` 为 main head `5874906ce19e836083b99954b4a7a972b8eec5bb`，工作树干净。未将它作为研究基线。
- `git ls-remote --heads origin` 确认任务远端 `task/research-three-two-hop-lineage-20261012` 仍为 **c5e77abf99e902ca9da0ffff7c6e782f56ffacb0**；从该提交创建独立分支 `task/research-three-config-provenance-20261021`，不合入 main。
- 阅读现存唯一 `研究方向调研-G1-G8/AGENTS.md`、该目录简报与交接、研究三 README、配对 PLAN、package README 和 10-14/15 入口门禁证据。根 AGENTS 不在此保存工作树，未推测其内容。
- 核对全部远端 task 分支与已有测试；未发现本工作树未提交用户修改或其他写入者。未找到统一活跃任务锁，无法据此声称外部任务不存在；通过新分支、限定本包补丁避免覆盖既有分支。
- 沿用 `PCG-IDENTIFIABILITY-PAIRED-CPU-001` 目标：诊断无信息不可辨识与增加合格边界信息后的行为；不改 M0、不把 UNKNOWN 当真值、不改变验收口径。

## 实际命令、失败与终态

以下开发命令均从 `package-v1` 运行；日志中本机 package 绝对路径统一替换为 `<package-v1>`，移除日志行尾空格，其余输出保留。

| 命令 | 实际终态 | 证据 |
|---|---|---|
| `python3 -I -B -m unittest discover -s tests -p test_execution_pin_inventory.py -v`（修改生产代码前） | exit 1，4 tests、24 failures；22 项缺失未拒绝、额外路径未拒绝、入口未按 pin 缺失阻断 | `EXECUTION_PIN_TEST_RED_20261021.log` |
| `python3 -I -B -m unittest discover -s tests -v`（修复后） | exit 0，58 tests PASS | `EXECUTION_PIN_TEST_GREEN_20261021.log` |
| `python3 -I -B runner.py --task-manifest TASK_MANIFEST.json --preflight-only` | exit 20，BLOCKED，四资源缺失，0 starts/0 completed | `CURRENT_MANIFEST_PREFLIGHT_20261021.json` |
| `docker version --format '{{json .}}'` | exit 0，client/server 28.4.0，Linux amd64 | `ENVIRONMENT_READONLY_20261021.json` |
| `docker info --format '{{json .}}'` | exit 0，cgroup v2，memory/swap/CPU quota/PID 控制能力自报 true | 同上（只保留相关字段） |
| Python stdlib `platform`、`os.geteuid/getegid`、`shutil.which`、socket 路径 access 与 `/sys/fs/cgroup/` 五项文件只读 | exit 0；详 JSON | 同上 |
| `git diff --check` | exit 0 | 无 whitespace error |

未执行资格容器、OOM 探针、镜像构建/拉取、安装、身份切换、权限提升、网络配置、正式 runner/scorer、旧失败重跑。当前 manifest preflight 在资源门禁返回，因此 `--preflight-only` 没有运行其后续会创建容器的资格步骤。测试入口使用 fake DockerSession，但断言没有调用它；synthetic fixture 中完整资源只存在临时文件，非批准或执行。

## 保存云环境已有能力与剩余阻塞

Linux 6.18.55 x86_64，Docker 本地 socket 可访问，daemon 自报 cgroup v2 及相关资源能力。当前云工作容器 `cpu.max=400000 100000`（4 CPU 上限）、`memory.max=17179869184`（16 GiB），`memory.swap.max=max`、`pids.max=max`。daemon 的 5 CPU/约 18.9 GB 容量是不同视角，不能当作方法容器限额或实测峰值。

当前有效 UID:GID **1000:1000**；runner 硬性要求 **65534:65534**，身份不匹配。这是观察到的门禁条件，不是自动审批拒绝；本轮没有尝试切换身份/提升权限。Linux/Docker “已有”不等于资格通过：隔离、OOM、实际限额、清理和资格证据均 **NOT_RUN/NOT_VERIFIED**。四资源值仍 null；私有 V2 主规格、schema、指标及版本来源链仍未提供，相关结论未知。

## 最小待决包（建议，未批准）

以下为保守的后续 profile 候选，**没有写入 TASK_MANIFEST、没有授权资格探针或正式运行**。无本任务运行测量，不能保证预算足够；任何调整须新冻结，不能同 run ID 调参重试。

| 字段 | 候选 | 理由与限制 |
|---|---:|---|
| `wall_seconds` | 600 | 覆盖 80 次串行容器启动/检查与一次资格步骤的候选生命周期预算，含现有 9 秒清理保留；剩余 591 秒并非全部可用于方法执行，未经 benchmark |
| `memory_bytes` | 268435456（256 MiB） | 纯 Python 小型合成输入的初始 per-container cap，超过固定 64 MiB OOM 资格探针最低需求；不宣称已测 peak RSS |
| `pids_limit` | 16 | 单解释器串行槽的候选进程/线程余量；需资格确认，不扩大宿主权限 |
| `max_method_output_bytes` | 9437184（9 MiB） | 累计 stdout+stderr 总 cap，80 槽均摊约 115.2 KiB；不是 per-slot cap，未经实测输出定标 |

需人工分别决定：是否采纳上述四值；是否提供一个按现有身份策略可合规运行的已授权执行上下文并单独授权资格步骤；若要做私有 V2 结论，提供钉版本权威材料。资源批准本身不等于正式 80 槽运行批准。本轮不等待决定，交付所有不依赖它们的代码、测试与证据。

## 独立复审与交接

独立 reviewer 只读审查补丁并独立运行 58 项 isolated tests：58/58 PASS、exit 0；确认 25 项精确集合及实际入口断言可信、TASK execution hashes 匹配、四资源仍 null。指出持久化 manifest 的 runner/TASK hash 与新增测试尚需更新，本次已纳入交付校验。复审不证明 Docker 资格、私有 V2 或研究效果。

后续先复核本次持久化 manifest，再处理上述人工决定；不要从本报告直接派发或执行正式实验。完整交付提交 SHA 与远端报告链接在本次最终交付消息中提供，以避免在提交自身内循环引用。
