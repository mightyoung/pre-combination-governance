from __future__ import annotations

import csv
import hashlib
import json
import random
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
MD_OUT = ROOT / "实验设计与执行计划v6.9-指定执行版-机制验证到确认性试验.md"
JSON_OUT = ROOT / "ExperimentExecutionPlan-v6.9.json"
CSV_OUT = ROOT / "MMEAllocation-v6.9.csv"

MASTER_SEED = 202607140609
METHODS = ["A", "B0_NAIVE", "B1_TRANSPORT_EOS", "B2_LINEAGE_ONLY", "B3_CAUTIOUS", "B4_PARTIAL_DEP", "B5_UNKNOWN_CORR"]
CORE_PROFILES = ["C0_UNIQUE_BASE", "C1_EXACT_RETRY", "C2_DISTINCT_KEY_PRE_EQ", "C3_POST_COMMIT_EQ_1", "C4_POST_COMMIT_EQ_3_REPLAY", "C5_SUPERSEDE", "C6_MERGE_RETIRE_REPLAY", "C7_REGISTERED_SHARED_ANCESTRY", "C8_GENUINELY_INDEPENDENT_ROOT"]
STRESS_PROFILES = ["S1_HIDDEN_MISSING_EDGE", "S2_SPURIOUS_EDGE", "S3_EVENTIFIER_OVERSPLIT", "S4_EVENTIFIER_OVERMERGE"]


PLAN_MD = r"""# 实验设计与执行计划 v6.9：指定执行版——从机制验证到确认性试验

> **状态：EXECUTION-SPECIFIED / REMOTE-RUN-BLOCKED。** 本版把 v6.8 的原则蓝图落实为阶段规模、随机化、门、责任和排期。它不修改已完成 SHK-000 的证据等级，不授权 pilot 或 `D_test`。当前 `G0_RESOURCE=FAIL`；允许继续本地实现和只读资格工作，但任何服务器 MME、pilot 或确认试验必须等待 G0–G4 相应门关闭。

## 0 一页执行摘要

| 阶段 | 独立单位与规模 | 目的 | 当前是否可启动 |
| --- | --- | --- | --- |
| Phase 0A | 本地 property/unit traces，不作为统计样本 | 完整 lifecycle runtime、第二实现、权限负测 | **可以，本地** |
| Phase 0B | 50,000 lifecycle traces + 1,000 crash/restart traces/实现 | Q1/Q2 工程资格 | G0 可未闭，但不得写远程实验命名空间 |
| MME-SCREEN | 24 strata × 4 physical seeds = **96 bundles** | 淘汰无区分力主线、发现实现/指标问题 | **不可以，须 G0–G2** |
| MME-VERIFY | 新的 24 × 4 = **96 bundles** | 对冻结 MME 结论作独立复核 | SCREEN GO 后才可 |
| D_select | 24 × 8 = **192 bundles** | 冻结唯一 G*；不进入主 test | MME GO + G3/G4 |
| Pilot-fit | 每 wave 24 × 4 = **96 bundles**；2–6 waves | 估 nuisance、tail、ICC、failure 与 joint kernel | G0–G4 + pilot 授权 |
| Pilot-heldout | 24 × 4 = **96 bundles** | 只验证 coverage/calibration/tail | fit 精度门通过后 |
| Confirmatory | 由 joint power 搜索决定；候选每层 (n_s\in\{8,12,16,24,32,48,64\}) | C-System/IUT 与 no-harm | 仅最终 manifest 授权后 |

**硬性决策：**如果 MME-VERIFY 不能证明 A 在外部 oracle 下解决了 simple transport exactly-once 和 lineage-only 至少一个无法处理的 post-commit 认知重复问题，停止当前 IF 创新主线，不进入昂贵确认试验。

## 1 研究问题、主张与版本边界

### 1.1 研究问题

1. A 是否在 exact retry、不同键同源、post-commit equivalence、supersede、merge、retire 与 replay 中保持每个 canonical class 至多一个当前认知贡献？
2. A 是否能在不拒绝真正独立新信息的前提下，比 transport exactly-once、lineage-only 与依赖组合近邻更接近 unique-root oracle？
3. 在固定两类 CSTR、共同服务合同与动作真值下，A 是否同时改善危险错误/方法失败和正确行动时延，并通过 availability、组件安全与资源 no-harm？

### 1.2 主张阶梯

| 层级 | 主张 | 证据 | 失败后允许措辞 |
| --- | --- | --- | --- |
| Q1 | lifecycle contribution conservation | 双实现 + property/differential traces | 失败即核心否证 |
| Q2 | registry-relative exclusion consistency | truth graph 错设压力曲线 | 只能声称 declared-graph conformance |
| M1 | fusion-specific increment | 两阶段外部-oracle MME | 失败则停止 exactly-once 创新叙事 |
| C-System | 系统共同主终点达到 SESOI 且全门通过 | 一次性确认试验 | 失败只报描述性结果 |
| C-HB | hazard–barrier 语义有独立增量 | 匹配 `A^-Topo` | 失败则过程安全仅是案例 |
| External | 独立 simulator/shadow/HIL 支持 | 冻结接口外部复现 | 未完成则只对两 CSTR strata 有效 |

`SESOI_risk`、`SESOI_delay`、availability/组件 no-harm margins 和 service caps 标记为 `PENDING_DOMAIN_SIGNOFF`。它们必须由过程安全负责人和统计负责人基于动作成本、业务容忍度和服务合同签署，不能从 MME 或 pilot 的 A−baseline 效应方向反推。

## 2 独立单位、分层、随机化与盲态

### 2.1 独立统计单位

唯一独立单位是 `physical_seed_base_bundle`：由物理参数、初始条件、扰动、故障时刻、屏障响应和事故路径共同产生的一条完整动力学轨迹。以下全部嵌套于 bundle，不增加 (n)：method、variant、noise seed、arrival seed、attack、algorithm seed、tick、窗口、视图、重放和同一 simulationRun 的所有时间点。

主比较是**配对重复测量设计**：每个 bundle 被全部方法读取；方法差异在 bundle 内求 paired contrast，再以 bundle 为 bootstrap/方差单位。禁止把 7 个方法、13 个 profile 或 4 个 noise×arrival 技术重复解释成 364 个独立样本。

### 2.2 24 个固定 strata

评价分布固定为 2 个 CSTR topology × 4 个预签事故路径族 P1–P4 × 3 个 severity band S1–S3，共 24 层，主分析权重暂定均等 (w_s=1/24)。P1–P4 的领域名称由 `ScenarioSupportManifest` 在任何 MME 数据生成前替换。任一层不可达时必须升版、删除并重新归一，不能在看结果后借用邻层。

连续物理参数在每层内用 seeded maximin Latin hypercube 覆盖；operating mode、barrier configuration 与 registered CCF level 用平衡置换分配。每个 replicate batch 包含 24 strata 各一个 bundle，是 randomized complete block；bundle 执行顺序和 bundle 内 7 个方法顺序均由 `MMEAllocation-v6.9.csv` 冻结。

### 2.3 盲态与权限

- 方法容器只见 opaque episode token 和 operational payload，不见 truth、frame、attack marker 或 ActionTruth；
- scorer 使用 scorer-only physical acquisition/ancestry graph，禁止读取 A 的 ledger 作为真值；
- 结果表先以匿名 arm code `M01–M07` 生成，主估计、失败映射和 QC 锁定后再解盲；
- allocation master seed、派生算法、容器 digest 与最终 CSV SHA 写入 SeedManifest；
- test 前任何人工不得同时拥有 truth store 写权限和方法容器执行权限。

## 3 方法臂与公平合同

| 臂 | 定义 | 必须实现的公平条件 |
| --- | --- | --- |
| A | v21 lifecycle-consistent pre-combination governance | 不得独享 truth、更宽 deadline 或额外传感输入 |
| B0 | naïve normalized conjunctive | 公开下界，不作为唯一主基线 |
| B1 | simple event-sourced transport exactly-once | 同 message/version key 幂等、checkpoint/replay；不使用物理 root oracle |
| B2 | provenance/lineage-only | 传播已知 ancestry、删除已知冗余祖先；无 A 的 safety transaction |
| B3 | cautious combination | 相同输入与 mapping，不附加 lineage truth |
| B4 | partial-dependence/ER-TLD 类强近邻 | 依赖参数只由允许校准集估计 |
| B5 | unknown-correlation conservative baseline | 只在公共 belief/risk 输出可比时进入 |

所有方法共享同一 raw bundle、SourceAdapter 输出、frame、deadline、CPU/memory cap、异常映射、日志粒度和 scorer。方法特异 timeout/OOM/crash 计失败，不重跑；若某基线无法输出共同 belief/credal-risk/action schema，必须在执行前冻结 loss-preserving adapter，不能在结果后选择有利映射。

## 4 Phase 0：实现和工程资格

### 4.1 可立即本地执行的任务

1. 完成 INITIALIZE、SUPERSEDE、MERGE、RETIRE、REPLAY、SAFE_HALT；
2. 实现独立的 pure-reference oracle，代码库、author/reviewer 与主 runtime 分离；
3. 建立 truth graph / declared graph 双图和 scorer-only 接口；
4. 生成 property traces，覆盖 exact retry、ABA、乱序、post-commit merge、crash/restart、cap overflow；
5. 建立容器/UID/ACL 负测脚本和零 `D_test` namespace 审计；
6. 冻结失败分类：contract failure、method failure、infrastructure failure，不得把失败样本删去。

### 4.2 指定规模与通过门

- 主实现和第二实现各运行至少 **50,000 条**随机 lifecycle traces；
- 另运行至少 **1,000 条**含 crash/restart/CAS retry 的 trace；
- 所有确定性输入的 online/replay state hash 100% 一致；
- 每个 canonical class 的 active contribution count 必须始终为 0 或 1；
- mandatory merge/replay 失败必须进入 UNAVAILABLE/SAFE_HALT；
- 双实现的 belief、registry、ledger、budget、gate 与 action 输出在冻结容差内 100% 一致；
- `pip check`、unit、property、integration、artifact hash、credential/path/ACL audit 全通过。

任何一次核心 invariant 失败都使 Phase 0 为 FAIL；修复后必须新建 qualification run，不得覆盖失败记录。

## 5 Phase 1：两阶段 Minimal Mechanism Experiment

### 5.1 分配与运行总量

SCREEN 和 VERIFY 使用互不重叠的 physical seeds，各为 24 strata × 4 replicate batches = **96 independent bundles**，总计 (n=192)。核心 9 profiles 对所有 192 bundles × 7 methods 执行；4 个错设 stress profiles 只在每阶段 replicate 1 的 24 bundles 上执行，并做 2 noise ×2 arrival 技术重复。

因此指定 method-run 总量为：

$$192\times9\times7 + 48\times4\times2\times2\times7 = 17{,}472.$$

该数字是执行次数，不是统计样本量；MME 的独立 (n) 仍是 96/阶段。

### 5.2 核心与压力 profiles

| ID | 操纵 | 主要区分对象 |
| --- | --- | --- |
| C0 | unique-root baseline | 正常响应与 availability |
| C1 | exact retry，同 key/envelope | 所有 exactly-once 实现应能处理 |
| C2 | 不同 transport key、同 acquisition，pre-commit equivalence | transport key 与 physical root 的区别 |
| C3 | 同源 root 已提交 1 次后才披露 equivalence | post-commit rollback/rebuild |
| C4 | 已提交 3 次后披露 equivalence，并含乱序 replay | 深历史重建与 action state |
| C5 | 同 root 的 higher-version supersede | 版本不是新证据 |
| C6 | merge → retire → checkpoint replay | 生命周期事务完整性 |
| C7 | 已登记 shared ancestry/common cause | registry-relative blocking |
| C8 | oracle 证明真正独立的新 root | 防止以拒绝一切获胜 |
| S1 | truth graph 有边、declared graph 漏边 | registry omission 边界 |
| S2 | declared graph 有伪边 | false block 与 availability |
| S3 | Eventifier over-split | root 粒度敏感性 |
| S4 | Eventifier over-merge | 独立信息损失 |

### 5.3 主要输出

对公共输出 (g_m) 报告：

$$DRI_m(k)=d\{g_m(X\cup D_k),g_m(X)\},\qquad
SRI_m(k)=d\{g_m(X\cup I_k),g_m(X)\}.$$

主要评价为与 unique-root oracle 的 belief (L_1)/Jousselme distance、credal-risk deviation、action-set disagreement、post-merge recovery error 和 time-to-recover。约束评价为 benign availability、false block、wrong-direction action、restricted delay、P99、peak memory、replay cost、timeout/OOM/crash。A 的 internal root count 只用于诊断。

### 5.4 精确资格门

1. C1–C6 中 A 的最终 belief/risk 与 unique-root oracle 误差 ≤(10^{-10})，exact retry hash 必须完全一致；
2. C0 与 C8 在 registry/mapping 完整有效时不得因 relation UNKNOWN 产生 false block；
3. C8 中 A 必须对真正独立信息作出与 oracle 同方向的响应，不能以恒定 ABSTAIN 通过；
4. C6 后 online 与 replay 的 registry/ledger/budget/gate/action state hash 100% 一致；
5. S1–S4 不用于伪造无条件保证，必须报告 coverage/false-link 与 output degradation 曲线；
6. 所有方法的异常均计入公共失败终点，A 不得以更宽资源或隐藏信息获益。

### 5.5 编辑 GO/NO-GO

SCREEN 只用于发现实现、指标和 baseline adapter 缺陷；修复会触发 MME 版本升版并重新生成独立 VERIFY。VERIFY 的 GO 必须同时满足：

- 六项精确资格门全部通过；
- 相对 B1 和 B2，A 在至少一个预签 post-commit profile 上消除达到 `delta_MME=PENDING_DOMAIN_SIGNOFF` 的 oracle risk deviation 或 action mismatch，并在新的 96 bundles 上复现；
- A 在 C0/C8 的 availability、independent-information response 和资源 cap 不违反预签 no-harm；
- 结论不依赖 A 的 ledger 计数或删除失败运行。

若 B1/B2 同样恢复 oracle、A 仅降低内部 root count、或 A 只靠 abstention 获益，则 `MME_VERDICT=NO_GO`，停止当前 IF 主线。MME 不用于调确认性 SESOI、margin 或效应方向。

## 6 Phase 2：D_select、pilot 与确认性设计

### 6.1 G* 选择

`D_select` 固定为 24 × 8 = **192 independent bundles**。按预签 safety loss、availability、deadline 和 resource constraints 选择唯一 G*；使用 2,000 次 bundle-level stratified bootstrap。G* winner frequency 必须 ≥0.90；否则停止单赢家主张，升版为固定多基线 simultaneous comparison。三个 sentinel baselines 固定进行 Holm 调整的支持性比较。

### 6.2 Pilot-fit 顺序 waves

每 wave 为 24 × 4 = **96 bundles**，最少 2 waves、最多 6 waves；每完成一 wave 只更新 nuisance summaries，不查看或使用 A−G* 效应方向。停止 fit 的条件全部满足：

1. 每个关键 paired discordant cell 的期望/有效计数 ≥20；
2. 零事件的单侧 95% 上界低于已签署资格容忍度；
3. delay P95 区间相对半宽 ≤20%，P99 ≤30%；
4. batch ICC 的 95% 区间宽度 ≤0.10，并用 UCB 进入功效 grid；
5. failure、miss mass 与 tail kernel 无未分类质量；
6. G* stability 仍 ≥0.90。

达到精度门后，另生成固定 **96 bundles** 的 `D_pilot_heldout`，只验证 nominal 95% kernel coverage 是否在 92%–98%、tail/calibration 和层间 transport；不得重新调模型或 margin。6 waves 后仍未通过则停止并升版，不进入 power。

### 6.3 共同主终点与 IUT

1. (Y^{UF}=I(Y^{US}\lor Y^F))：unsafe-SAFE 或方法失败；并分别对 (Y^{US}) 与 (Y^F) 设置 no-harm；
2. restricted correct-action delay：错误方向、超时、无动作、窗口内失败均不能完成终点。

绑定门包括 benign SAFE availability、miss mass、误升级、拒判、barrier calibration、demand sensitivity、P99、memory/OOM、update/query budget 和 SAFE invariant。每个共同主组件使用单侧 (alpha=0.025)；IUT 不在组件间再拆 alpha。支持性多基线使用 Holm。

### 6.4 联合功效与最终样本量

使用与最终分析完全一致的 Monte Carlo pipeline；每个候选容量至少 **10,000 replicates**，并用独立 `power-confirm` seed/container 复核。每个 replicate 重做 physical/batch generation、G* selection、全部方法、failure mapping、paired stratified bootstrap、所有 no-harm/gate 和盲态 SSR。

候选 analyzable 容量为每个 retained stratum (n_s\in\{8,12,16,24,32,48,64\})。最终 (n) 是满足以下条件的最小点：

- 完整 gate 的 joint pass probability Wilson 95% 下限 ≥0.90；
- null grid 下每项 claim 的 Type-I Wilson 95% 上限 ≤0.025；
- 失败/不收敛 replicate 计未通过；
- nuisance grid 覆盖 ICC UCB、failure、discordance、tail、G* instability 与 layer weights；
- 预计存储、CPU/GPU、人力和归档均低于冻结 (n_{max,budget})。

若 (n_s=64) 或预算上限内仍无合格点，则 `C-System=NOT_TESTED`；禁止删终点、放宽 no-harm 或生成 `D_test`。仅允许升版定义更窄主张并用独立数据重新确认。

## 7 数据分区、ActionTruth 与防泄漏

命名空间严格分离：`D_impl_unit`、`D_mapper_cal`、`D_mapper_qual`、`D_mme_screen`、`D_mme_verify`、`D_select`、`D_pilot_fit`、`D_pilot_heldout`、`D_test`、`D_external`。每个分区绑定独立 master key、生成器/数据版本、容器 digest、ACL 和只读 manifest。

独立过程安全团队在任何 pilot/test seed 前双签 `ActionTruthRuleManifest`、允许动作集合、deadline、禁止动作、generator/scorer code/hash 和争议处理。bundle ActionTruth 由规则自动生成；100% 机器资格 + severity×topology×path 分层人工抽审。禁止逐 bundle 人工编辑和看输出后改 truth。

`D_test` 当前不得生成。授权前必须同时满足：MME GO；G0–G4 全闭；pilot heldout 通过；joint power 与 Type-I 通过；全部 PENDING 域参数已签；TestManifest、AllocationManifest、SeedManifest、container digest 和 ACL negative test 均通过。

## 8 资源门与服务器执行条件

远端实测为 NVIDIA L20 46,068 MiB，但启动时有共享服务、GPU 利用率 100%，文件系统可用空间约 23.02%，故 G0 失败。计划按以下硬门执行：

1. 35 GB SHK-001 前可用空间必须 ≥270,853,007,872 bytes，即至少再释放约 54 GB（若按 35 GiB 则至少约 57 GB）；
2. 完整高包络约 3.068 TB；在结束时保留 25% headroom 需要至少约 **4.091 TB 可用总容量**，不能把 4 TB 标称盘视为足够；
3. GPU 仅在 server owner 签署独占/并发 quota 后使用，不能把全部 46 GB 显存当作本项目资源；
4. truth/scorer 与 methods 必须独立 UID/container，method mount 不可见 truth；
5. SCREEN 先设置 35 GB artifact cap；微基准若预测 P95 超 cap，停止并重签存储方案，不边跑边删；
6. 输出路径非空、candidate 可写、SHA 不匹配、ACL 负测失败、空间不足、OOM/Xid/ECC、未分类基础设施失败或资源日志缺失均立即退出。

G0 失败期间允许：本地 runtime、第二实现、property tests、schema/manifests、静态 baseline adapter 和不写实验命名空间的 dry run。禁止：远程 SHK-001、MME、pilot、功效结果晋级或任何 `D_test` 操作。

## 9 RACI 与签署责任

| 工件/门 | 负责 R | 最终 A | 协作 C | 隔离/复核 I |
| --- | --- | --- | --- | --- |
| runtime/ledger/replay | 方法实现负责人 | 项目负责人 | 基线负责人 | 独立验证负责人 |
| CSTR/24 strata/ActionTruth | 过程安全负责人 | 项目负责人 | 生成器负责人 | 两名独立安全复核者 |
| oracle/第二实现 | 独立验证负责人 | 质量负责人 | 方法负责人只提供接口 | 统计负责人 |
| randomization/power/SAP | 统计负责人 | 项目负责人 | 过程安全负责人 | 盲态分析负责人 |
| server/ACL/storage | 基础设施负责人 | 数据治理负责人 | 方法与评分负责人 | 独立安全审计 |
| GO/NO-GO 编辑结论 | EIC 模拟审查人 | 项目负责人 | 全体角色 | 不参与实现的外部复核者 |

同一人不得同时担任 truth/scorer 写入者和确认性方法运行者；主实现作者不得单独签署第二实现等价；统计负责人不得在解盲前接触 arm mapping。

## 10 24 周执行计划与 4 周缓冲

| 周 | 阶段 | 指定任务 | 退出物 |
| --- | --- | --- | --- |
| W1–2 | G0 | 独立存储/配额、ACL 设计、server profile、RACI、ClaimRegister | `G0ResourceManifest` |
| W1–5 | Phase 0A | lifecycle runtime、root mapper、第二实现、truth graph | code/container hashes |
| W5–6 | Phase 0B | 50k property + 1k crash traces/实现、差分资格 | `Phase0QualificationManifest` |
| W7 | MME-SCREEN | 96 bundles，冻结 17,472-run 计划的 SCREEN 部分 | screen report；不作论文主张 |
| W8 | 修复/冻结 | 仅修实现/adapter/指标，不改核心 hypothesis | `MMEPreregistration` v6.9.x |
| W9 | MME-VERIFY | 新 96 bundles，一次性复核 | GO/NO-GO 编辑结论 |
| W10–11 | G1/G3/G4 | 24 层资格、mapper qual、方法与公平合同 | Scenario/Method manifests |
| W12 | D_select | 192 bundles，G* stability | `GStarSelectionManifest` |
| W13–15 | Pilot-fit | 96-bundle waves，最多 6 waves | nuisance/kernel freeze |
| W16 | Pilot-heldout | 独立 96 bundles | coverage/tail verdict |
| W17–18 | Power | 10k/容量 search + 独立 confirm + null grid | `JointPowerSurface` |
| W19 | Freeze | SAP、SESOI/margins、Allocation/Test/Seed manifests | 可预注册 release |
| W20 | Dry run | one-shot empty-output rehearsal、独立复算 | dry-run audit |
| W21 | Confirm | 仅在授权后一次生成/运行 `D_test` | immutable run ledger |
| W22 | Analyze | 盲态主分析、第二容器复算、一次解盲 | locked result tables |
| W10–23 | External | 独立 simulator/shadow/HIL 至少一项 | transportability report |
| W23–24 | Paper | v22 结果稿、匿名复现包、投稿配套件 | submission candidate |
| W25–28 | Buffer | 仅供 test 前升版或外部复核延迟 | 不得追逐阳性结果 |

若任一前置 gate 延迟，后续任务顺延；不得通过并行解封下游数据“追回进度”。

## 11 版本包与停止条件

最低交付：

- `ExperimentExecutionPlan-v6.9.json`；
- `MMEAllocation-v6.9.csv` 及 SHA-256；
- `Phase0QualificationManifest.json`；
- `MMEPreregistration.json`、SCREEN/VERIFY manifests 与 GO/NO-GO；
- `ScenarioSupportManifest.json`、`ActionTruthRuleManifest.json`；
- `GStarSelectionManifest.json`、`JointPowerSurface.json`；
- `AllocationManifest.json`、`TestManifest.json`、`SeedManifest.json`；
- environment freeze、container digest、resource log、failure ledger 与独立复算报告。

全局停止条件：核心 invariant 失败；MME NO_GO；24 层或动作真值无法双签；G* 不稳定且未升版；预算内无联合功效点；G0/ACL/manifest/hash 任一失败；出现 test 泄漏、选择性重跑或结果后改 margin。停止不是“实验失败”，而是阻止不可解释结果进入论文。
"""


def derive_seed(rng: random.Random) -> int:
    return rng.randrange(1, 2**63 - 1)


def build_allocation() -> list[dict[str, object]]:
    rng = random.Random(MASTER_SEED)
    rows: list[dict[str, object]] = []
    for phase in ["SCREEN", "VERIFY"]:
        for replicate in range(1, 5):
            batch_rows: list[dict[str, object]] = []
            for topology in ["T1", "T2"]:
                for path_family in ["P1", "P2", "P3", "P4"]:
                    for severity in ["S1", "S2", "S3"]:
                        method_order = METHODS[:]
                        rng.shuffle(method_order)
                        row = {
                            "phase": phase,
                            "replicate_batch": replicate,
                            "block_id": f"{phase}-R{replicate}",
                            "topology": topology,
                            "path_family": path_family,
                            "severity": severity,
                            "stratum": f"{topology}-{path_family}-{severity}",
                            "physical_seed": derive_seed(rng),
                            "noise_seed_primary": derive_seed(rng),
                            "arrival_seed_primary": derive_seed(rng),
                            "robustness_subset": replicate == 1,
                            "noise_seed_secondary": derive_seed(rng) if replicate == 1 else "",
                            "arrival_seed_secondary": derive_seed(rng) if replicate == 1 else "",
                            "method_order": "|".join(method_order),
                            "core_profiles": "|".join(CORE_PROFILES),
                            "stress_profiles": "|".join(STRESS_PROFILES) if replicate == 1 else "",
                        }
                        batch_rows.append(row)
            rng.shuffle(batch_rows)
            for run_order, row in enumerate(batch_rows, start=1):
                row["run_order_within_block"] = run_order
                rows.append(row)
    return rows


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def main() -> None:
    rows = build_allocation()
    fieldnames = list(rows[0].keys())
    with CSV_OUT.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    phase_counts = {phase: sum(r["phase"] == phase for r in rows) for phase in ["SCREEN", "VERIFY"]}
    stratum_counts: dict[str, dict[str, int]] = {}
    for phase in ["SCREEN", "VERIFY"]:
        stratum_counts[phase] = {}
        for row in rows:
            if row["phase"] == phase:
                key = str(row["stratum"])
                stratum_counts[phase][key] = stratum_counts[phase].get(key, 0) + 1

    contract = {
        "schema": "experiment-execution-plan-v6.9-1.0",
        "status": "EXECUTION_SPECIFIED_REMOTE_BLOCKED",
        "master_seed": MASTER_SEED,
        "independent_unit": "physical_seed_base_bundle",
        "strata": {"topologies": 2, "path_families": 4, "severity_bands": 3, "total": 24, "primary_weights": "uniform_1_over_24"},
        "mme": {
            "screen_bundles": 96,
            "verify_bundles": 96,
            "total_independent_bundles": 192,
            "methods": METHODS,
            "core_profiles": CORE_PROFILES,
            "stress_profiles": STRESS_PROFILES,
            "robustness_subset_bundles": 48,
            "specified_method_runs": 17472,
            "go_gate": "all exact qualification gates plus held-out external-oracle increment over B1/B2 without availability/SRI/resource no-harm failure",
            "pending_domain_inputs": ["delta_MME", "availability_no_harm", "service_caps"],
        },
        "selection": {"bundles": 192, "per_stratum": 8, "bootstrap_replicates": 2000, "winner_stability_min": 0.90},
        "pilot": {
            "wave_bundles": 96,
            "bundles_per_stratum_per_wave": 4,
            "min_waves": 2,
            "max_waves": 6,
            "heldout_bundles": 96,
            "precision_gates": {"discordant_cell_min": 20, "p95_relative_halfwidth_max": 0.20, "p99_relative_halfwidth_max": 0.30, "icc_interval_width_max": 0.10, "nominal_95_coverage_range": [0.92, 0.98]},
        },
        "confirmatory_power": {
            "candidate_n_per_stratum": [8, 12, 16, 24, 32, 48, 64],
            "monte_carlo_replicates_per_point_min": 10000,
            "joint_power_wilson_lower_min": 0.90,
            "type1_wilson_upper_max": 0.025,
            "component_alpha_one_sided": 0.025,
            "pending_domain_inputs": ["SESOI_risk", "SESOI_delay", "component_no_harm_margins", "n_max_budget"],
        },
        "resource_gates": {
            "current_G0_RESOURCE": "FAIL",
            "shk001_min_free_bytes": 270853007872,
            "minimum_additional_free_bytes_decimal_35GB": 53670873600,
            "full_high_envelope_bytes": 3068041987700,
            "minimum_total_capacity_with_25pct_headroom_bytes": 4090722650267,
            "pilot_authorized": False,
            "d_test_authorized": False,
        },
        "allocation": {
            "file": CSV_OUT.name,
            "rows": len(rows),
            "phase_counts": phase_counts,
            "stratum_counts": stratum_counts,
        },
    }
    JSON_OUT.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")
    contract["allocation"]["sha256"] = sha256(CSV_OUT)
    JSON_OUT.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")
    MD_OUT.write_text(PLAN_MD.rstrip() + "\n", encoding="utf-8")

    assert len(rows) == 192
    assert phase_counts == {"SCREEN": 96, "VERIFY": 96}
    assert all(count == 4 for phase in stratum_counts.values() for count in phase.values())
    assert sum(bool(r["robustness_subset"]) for r in rows) == 48
    print(json.dumps({"markdown": str(MD_OUT), "json": str(JSON_OUT), "csv": str(CSV_OUT), "rows": len(rows), "allocation_sha256": contract["allocation"]["sha256"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
