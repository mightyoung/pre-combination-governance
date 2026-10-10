# GitHub Actions 有界 CPU 资格路线（只读评估，2026-10-10）

专用saved cloud environment暂时无法注册；它不应是唯一前置。GitHub Actions可作为待审查的Linux候选执行平台，但当前未创建工作流、未触发run、未改main，也未公开新实验包。本轮授权仍只为进度文本与静态路线评估。

## 现有仓库与权限

只读API确认仓库public、当前账号push/admin权限；既有交接分支task/research-handoff-v1和开放PR1用于reviewable commits。Actions enabled=true、allowed_actions=all，当前workflow数量0；main protection API报告未保护。这不授予自行合main的权限。GitHub CLI先前GraphQL PR编辑缺read:org范围，已用既有repo权限REST编辑成功，未扩大token范围；正常API文档推送已核验。当前权限可以在获授权后提交独立研究分支的workflow草稿，是否实际执行仍是另一决定。

GitHub官方规则：workflow_dispatch需工作流在默认分支登记，之后可选择其他ref。只把全新workflow放交接分支不保证可手动触发；不能以push/pull_request/repository_dispatch自动计算或临时改默认分支规避。故先独立分支草稿/PR审核；若最终采用Actions，需要用户另批准最小默认分支手动入口的登记/合并，并再明确一次运行授权。见[手动运行工作流](https://docs.github.com/actions/managing-workflow-runs/manually-running-a-workflow)。

## 不同于直接复用Mac包

研究代码/科学输入保持Linux清单所述的固定字节；修改范围只为Linux隔离launcher、运行时指纹、监督适配、构建身份与平台资格。BUILD005-r2完整Mac ZIP含Mac运行时绑定/路径，不能直接公开或执行。GitHub只有源码与旧smoke文本和最新脱敏摘要；没有新S2完整包。完整Mac ZIP 1,315,572 bytes/SHA eeba84f69768c86109017f462fbbd4224646d09b2745ee46f08e94f6a83cdf11，manifest a24c9906645e3c5969d0ba7260bfbdde0644f71686d6a2023cfd1ef4b2bb2559，仅用于原件身份。

可以另审查最小公开派生文本：固定公开源码需要的vendor/worker/observer/contracts、同字节S2纯合成public输入/sidecar/reference/schema、Linux launcher/资格规范和清单。S2材料无真实数据、host路径或审批凭据，适合做脱敏公开候选，但本轮没有获得新材料公开授权；须先确定文件allowlist并人工批准公开。移除Mac runtime-binding/真实permit/原始日志/工具状态，不发布.omx/datasets/archive；保留科学bytes并对派生包新SHA独立审核。

已知私有传输途径没有可用确认位置：Library prepare_uploads此前能力缺失、无ID；Drive无确认文件ID，本轮未搜索或上传；GitHub仓库public，Actions artifacts不是私密仓库。官方说明有repository read access的已登录用户可下载artifact，因此不能把原包/路径/原日志上传artifact当私有传输。见[下载Artifacts](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/download-workflow-artifacts)。若材料不可公开，则必须先有获批准的私有来源及读取权限；与“无新secret/无新外传”同时不具备时停止，不填临时URL或PAT。

## 工作流草案应有的具体边界（当前没有YAML）

仅workflow_dispatch，无push/PR/schedule自动触发；单job、无matrix、无自动retry。checkout冻结完整commit SHA并核对manifest/blob，禁止任意ref/命令/URL输入；所有外部action也固定完整SHA，persist-credentials=false。GITHUB_TOKEN只需contents:read，不给写repo/PR或OIDC权限；无自定义secrets、私有凭据/云token/外部服务。worker/controller实验子环境不继承GitHub runner的认证/代理/秘密变量，只有冻结最小env，原始env不得写日志。控制平面只从已批准GitHub固定材料获取与发布允许摘要，实验层无网络，不能把checkout/runner自带网络当隔离通过。

runner限标准GitHub-hosted Linux CPU，无larger runner/GPU/付费选项；官方public标准runner运行免费，但artifact/cache的共享存储可能计费，当前账号剩余存储未核验。因此第一版不建cache、不上传artifact，仅保存小型脱敏job summary与SHA；如需上传失败证据artifact，先明确批准allowlist、大小（建议<=64KiB脱敏JSON）、retention（建议1天）及零费用条件，不上传raw logs/完整包。见[Actions计费](https://docs.github.com/en/billing/concepts/product-billing/github-actions)。

在任何计算前只读检查runner已有Python/依赖/隔离工具与namespace/procfs/cgroup权限。缺包、等效隔离或owned进程可见性则BLOCKED，不apt/pip install、不拉容器镜像、不改sysctl/安全设置。机器镜像标签非字节冻结；应记录runner镜像版本/架构及实际Linux依赖指纹，不能称与Mac相同runtime。

平台job timeout可设5分钟作为checkout、摘要和cleanup的外层保险，但不是给实验5分钟；新资格+两worker仍使用同一个120wall/60CPU ledger，worker25wall、单512MiB/总2GiB RSS、输出10MiB，45wall/8CPU/1MiB资格子限额包含总额。摘要/setup等控制工作另给明确小上限并单独报账，若整job必须总120秒则需预先重算/冻结分配，不能默许额外CPU。具体外层setup/摘要限额尚待草案审核，不据此启动。jobs timeout-minutes是分钟级保护，不能替代CPU/RSS累计监督；见[Workflow语法](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)。

concurrency防同计划同时跑，cancel-in-progress=false避免覆盖失败证据。bootstrap/guardian可读owned /proc并受控停组/回收；worker使用实际新Linux等效隔离，只读代码/runtime、公有pipe输入，无oracle/sidecar读权、无写/无fork/无出网。namespace/bwrap失败即停，不裸跑。新16资格全部通过才启动2worker/6checkpoint，失败不续跑。TERM→有界grace→KILL→wait、组成员与CPU/output/RSS最终账本均保存；AccessDenied/枚举不完整只能UNKNOWN/FAILED，不PASS。最终保存动作须在预算余量内；runner被强制终止时after-step可能来不及执行，因此缺final receipt保留UNKNOWN，不能假定always()保证cleanup或证据完整。

Mac与Actions Linux时序单独报告；本路线即使成功仍只属于已曝光的S2开发正确性覆盖，不是D07、MME正式准入或性能比较。正式预注册存在性UNKNOWN、D07未执行保持原状。

## 最小新增授权问题

首先只需决定：是否允许在研究分支准备并提交“仅手动触发的Linux资格工作流草稿＋经allowlist审查的最小脱敏合成文本派生包”，不合main、不触发运行、不安装依赖、不付费？

若草案审查通过，随后才决定两个具体动作：最小手动入口登记到默认分支；一次固定SHA/预算的新平台资格（全过后才两worker）。这两个动作当前均未授权，不能把同意路线当无限运行批准。若不允许新合成输入/适配代码公开且没有批准私有来源，Actions路线材料阻断。
