from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "00-论文-中文阅读稿v20.1-一致性修复与投稿主线收敛版.md"
MAIN_OUT = ROOT / "00-论文-中文阅读稿v21-生命周期一致组合前治理与IF创新主线版.md"
PLAN_OUT = ROOT / "实验设计与执行计划v6.8-机制先行与表示中立验证蓝图.md"
REPORT_OUT = ROOT / "研判报告二十四-报告二十三裁决与v21-Information-Fusion创新性论证.md"


def replace_section(text: str, start: str, end: str, replacement: str) -> str:
    a = text.index(start)
    b = text.index(end, a)
    return text[:a] + replacement.rstrip() + "\n\n" + text[b:]


HEADER = r"""# 谱系依赖信念融合的生命周期一致组合前治理：注册表相对准入与根级贡献守恒

*Lifecycle-Consistent Pre-Combination Governance for Lineage-Dependent Belief Fusion: Registry-Relative Admission and Root-Level Contribution Conservation*

## 摘要

多源信念融合系统常把传输重试、派生视图、模型版本和异步重放视为不同消息，但这些消息可能只对应同一次物理采集。现有依赖组合、provenance、谱系编码与 exactly-once 数据处理分别处理相关性、可追踪性、冗余祖先或传输重复，却没有自动规定：当两个已提交根在事后被证明等价，或根发生 supersede、merge、retire 与 replay 时，非幂等信念组合中的认知贡献、预算和安全行动资格应怎样原子重建。本文为此定义一种面向证据组合的 exactly-once 准入语义。它以物理采集事件为根，以独立的物理耦合与观测谱系注册表为组合资格证据，以一次 root-level joint mapping 形成唯一贡献，并以可重放账本在生命周期事件中保持根级贡献守恒。一个最小反例表明，两个具有不同消息键但来自同一采集的简单支持函数即使各被传输层“恰好处理一次”，仍会把质量从 0.80 虚增至 0.96；事后等价合并需要撤销并重建认知状态，而不仅是消息去重。本文只给出注册表相对的条件保证，不把未知依赖自动判为独立，也不把接受分支的 (1/\delta) 界作为主要理论创新。当前 SHK-000 仅完成 25 项工程测试与 16/16 窄 canary，资源门仍失败，未形成性能证据。本文进一步给出外部 oracle 驱动的最小机制实验与门控确认性设计，用于区分真实重复抑制、错误阻断和“永远拒绝”。

关键词：信念函数；证据谱系；组合前治理；exactly-once；生命周期一致性；过程安全

## Abstract

Multi-source belief-fusion systems often treat retries, derived views, model versions, and asynchronous replays as distinct messages although they may originate from one physical acquisition. Existing dependence-aware combination, provenance, lineage encoding, and exactly-once stream processing address correlation, traceability, redundant ancestry, or transport duplication, but they do not by themselves specify how epistemic contribution, commitment budgets, and safety-action eligibility should be rebuilt when committed roots later become equivalent or undergo supersession, merge, retirement, and replay. We define evidence-specific exactly-once admission semantics for non-idempotent belief combination. Physical acquisition events act as roots; separate physical-coupling and observation-lineage registries provide positive, registry-relative admission evidence; a single root-level joint mapper produces one contribution; and a replayable ledger conserves that contribution across lifecycle events. A minimal counterexample shows that two distinct transport keys from one acquisition can each be processed exactly once while duplicate simple-support functions inflate mass from 0.80 to 0.96. Correcting the state after post-commit equivalence therefore requires epistemic rollback and deterministic reconstruction, not message deduplication alone. Guarantees remain conditional on registry coverage, eventification, and mapping validity. The accepted-branch (1/\delta) bound is treated as supporting analysis rather than the main novelty. The current SHK-000 run provides only narrow engineering qualification: 25 tests and 16/16 canary checks passed, while the resource gate failed and no performance claim is supported. We therefore specify an external-oracle minimal mechanism experiment and a gated confirmatory design that jointly measure duplicate suppression, responsiveness to genuinely independent evidence, availability, and decision consequences.

Keywords: belief functions; evidence lineage; pre-combination governance; exactly-once semantics; lifecycle consistency; process safety
"""


SYMBOLS = r"""## 符号与缩略语

| 记号 | 含义 |
| --- | --- |
| root / view | 一次物理采集事件 / 由该事件产生的表达、派生或版本化视图 |
| (\mathcal E(r)) | root (r) 所在的可验证等价类 |
| SafetyArtifactIR | 过程安全工件经类型检查后的有限语义前端 |
| PCR / OLR | PhysicalCouplingRegistry / ObservationLineageRegistry |
| RootClaimBundle | 一个 canonical root 经一次联合 mapping 形成的唯一 joint valuation |
| (\mathsf X_k) | belief、registry、ledger、budget、gate 与 rate 的原子系统状态 |
| MME | Minimal Mechanism Experiment，非确认性的最小机制实验 |
| DRI / SRI | 冗余扰动不变性 / 独立信息响应指标 |
| IUT / SESOI | 交并检验 / 最小业务重要效应 |
| (R_u^-,R_u^+,W_u) | 效用 (u) 下的风险下界、上界与宽度 |
| (\mathcal A_i^*(t)) | tick (t) 的可接受安全行动集合 |
"""


INTRO = r"""## 1 引言

动态过程安全融合需要同时处理工艺偏离、屏障状态、报警、检维修、人工记录和派生分析 [3–6], [9–12], [24], [35], [46]。这类输入的困难不只是噪声或冲突：同一物理采集可被多个 adapter、窗口、模型、主体和版本重新表达；两个起初被当作独立的根，也可能在提交后才由校准记录、总线拓扑或审计证据证明同源。对归一合取等非幂等组合，消息被“各处理一次”不等于物理信息“只贡献一次”。

现有研究已经覆盖依赖证据、部分依赖、cautious rule、未知相关、来源行为解释和冲突处置 [17–23], [25], [27], [30–34], [37–44]。Yu 等利用 provenance 避免 Dempster–Shafer 信任评估中的 double counting [26]；Kowalski 与 Martin 跟踪 belief-function combination 的 provenance [13]；PRIMEX-PEV 编码分布式融合谱系并消除冗余祖先 [36]。流处理 exactly-once 研究则强调事件、状态和重放的一致提交 [45]。这些成果构成本文的直接近邻，因此本文不把 provenance、去重、event sourcing、Dempster 组合或“只计一次”单独宣称为新颖。

尚缺的对象是**信念组合特有的生命周期一致准入语义**：若 post-commit root equivalence、version replacement、merge、retire 或 replay 改变了“哪些消息代表同一认知贡献”，系统必须同步重建 belief、贡献账本、承诺预算、可用性和安全行动资格。普通 transport idempotency 能阻止同一键重复提交，却不能决定两个不同键是否是同一物理信息；provenance 能记录来源，却不必然规定等价发现后的原子撤销与重建；依赖组合规则能保守合成，却不负责 root 身份和生命周期事务。

本文回答三个问题：

1. 如何区分 transport exactly-once 与 epistemic exactly-once，并给出普通去重无法处理的最小反例？
2. 如何在未知依赖保持 UNKNOWN 的前提下，只凭正向、可审计且声明完备的证据准入 root contribution，并在生命周期事件中保持贡献守恒？
3. 如何用不读取本文内部 ledger 的外部 oracle 验证重复抑制、独立信息响应、错误阻断和决策后果，而不是用本文自己的表示为自己评分？

本文贡献及其当前证据状态如下。

| 贡献 | 内容 | 当前状态 |
| --- | --- | --- |
| C1：fusion-specific exactly-once semantics | 把 canonical root 的唯一认知贡献、post-commit equivalence、supersede、merge、retire、replay、预算与动作资格放入一个原子状态转换合同 | **规范化并有窄性质测试；尚未获得完整独立实现验证** |
| C2：正证据、注册表相对的组合前准入 | PCR 与 OLR 分离物理耦合和生成谱系；只有覆盖声明图的集合级证书可准入，缺失为 UNKNOWN | **条件命题；不保证真实世界注册表完备** |
| C3：表示中立的证伪路径 | 以外部 latent acquisition/ancestry oracle 构造 MME，并以 availability、false block、正确行动和资源门约束确认性主张 | **设计完成；未执行，不构成经验贡献** |

图 1 给出主链。过程安全工件只提供有限领域约束；原创性核心位于组合前准入和提交后生命周期重建，而不是工件本体本身。

![图1：安全工件到在线溯源约束融合闭环](figures/图1-安全工件到在线融合闭环-v20.png)

**图 1. 从约束工件到生命周期一致融合。** SafetyArtifactIR、PCR/OLR、root-level mapper、SetwiseEligibilityCertificate、原子 ledger 和 safety latch 形成闭环。字段级 schema、路由枚举与失败码下沉至 S2-v20.1；本文保留问题、状态、反例、核心语义和可否证主张。
"""


RELATED = r"""## 2 相关工作与研究定位

### 2.1 依赖信念组合与未知相关

Dempster–Shafer 理论及 TBM 提供信念表示和决策基础 [14–16]。Dempster 组合需要可辩护的 distinct bodies of evidence；内容相似既不能证明同源，也不能证明独立 [17], [39]。cautious rule、部分依赖组合、ER/ERr-DE/ER-TLD、上下文折扣和时间衰减分别处理非 distinct、参数化依赖、可靠性与时滞 [18–20], [32], [33], [38], [40], [41]。IFNet 与 covariance-intersection 类方法处理未知相关 [25], [31]。这些方法主要改变“怎样组合”或“怎样保守估计”，并不定义 root 的版本、等价类或 post-commit rollback。

### 2.2 Provenance、谱系与 double counting

belief-function provenance 已被用于解释组合过程 [13]；provenance-aware trust assessment 已直接以来源信息避免 double counting [26]；PRIMEX-PEV 用可扩展编码保留信息谱系、删除冗余祖先并支持异步更新 [36]。PROV-O 提供主体、活动、实体和派生关系的交换模型 [28]。因此，“使用 provenance”“传播 lineage”或“删除重复祖先”不是本文的新颖性。

本文研究的增量是时间顺序和事务后果：等价关系可能在两个 root 已进入非幂等组合之后才成立；旧版本可能被新版本替换；多个 active roots 可能被 merge；root 可能 retire 后触发 replay。此时 provenance 图只是证据，仍需一个规范决定撤销哪个 contribution、怎样重编译、怎样保留不可退款的历史 charge，以及何时禁止 SAFE 输出。

### 2.3 流处理 exactly-once 与 fusion-specific gap

流处理系统通过幂等键、checkpoint 和状态一致提交实现 exactly-once 或可重放语义 [45]。该语义通常以事件键或 operator state 为边界。对信念融合，真正的重复单位却可能在消息到达后才由外部证据确定，并且两个不同消息键可属于同一物理采集。本文因此借用事务纪律，但不把系统 exactly-once 重新命名为融合创新；需要验证的增量是：**普通事件级 exactly-once 在 post-commit epistemic equivalence 下是否仍产生不同于 unique-root oracle 的 belief 或行动。**

### 2.4 过程安全约束前端

动态屏障、可达性与多源风险更新为高约束验证域 [3], [4], [9–12], [24], [46]。ACCESS 与 Andromeda 把 assurance case 连接到异构工程工件 [5], [6]；FTA、Bow-Tie、LOPA 和 HAZOP 分别表达顶事件结构、危险路径、IPL 属性和偏差语义 [1], [8], [10], [35], [47], [48], [50]。这些工件不能自动证明观测独立或 Dempster distinctness。SafetyArtifactIR 因而只是有限语义前端：它约束 demand、barrier、loss 和禁止推理，不承担通用本体或独立性证明。

### 2.5 最近邻差异矩阵

| 最近邻 | 已解决 | 尚未自动解决 | 本文的可检验增量 |
| --- | --- | --- | --- |
| provenance-aware DS [13], [26] | 来源追踪、double counting 规避 | 提交后等价、版本替换和多状态原子重建 | post-commit equivalence 最小反例与 MME |
| PRIMEX-PEV [36] | 可扩展 lineage、冗余祖先消除、异步更新 | process/observation 双注册表、UNKNOWN 准入与 safety-action transaction | lineage-only 强基线 |
| transport exactly-once [45] | event/operator state 一致提交与重放 | 不同键之间的物理等价、认知贡献撤销 | 简单 event-sourced exactly-once 基线 |
| partial/cautious/unknown-correlation [18], [20], [25], [31], [40], [41] | 依赖或未知相关下的保守组合 | root identity、supersede/merge/retire/replay | 公共 oracle 和公共行动尺度比较 |
| safety-artifact frameworks [5], [6] | 工件连接、追踪和持续保证 | 工件语义如何限制信念准入 | 编译正负测试；领域增量单独检验 |

可成立的新颖性不是“把几个已知组件放在一起”，而是一个可被反例否证的组合语义：**对非幂等信念融合，把 physical-acquisition root 的唯一认知贡献与其提交后生命周期绑定，并使 belief、ledger、budget、availability 和 action eligibility 在同一事务边界内重建。** 若简单 event-sourced baseline 在外部 oracle 下同样满足这些性质，本文核心主张即不成立。
"""


METHOD = r"""## 3 问题模型与约束接口

### 3.1 状态、根与威胁边界

系统处理的不是裸消息，而是带认证身份、物理采集区间、因果边界、adapter 版本和 mapping 证书的候选 view。canonical root 表示一次物理采集或独立观察事件；设备、人员或文件本身不是 root。同一设备在不同有效 epoch 可产生新 root，重采样、滑窗、摘要、转录和模型重跑默认继承原 root，除非有正向证据证明新的物理采集。

原子系统状态为

$$
\mathsf X_k=(\mathbb B_k,\ \mathrm{RootRegistry}_k,\ \mathrm{ActiveContributionLedger}_k,\ \mathrm{BudgetState}_k,\ \mathrm{GateState}_k,\ \mathrm{AcceptanceRateState}_k).
$$

威胁模型覆盖：exact retry、不同键重复、乱序、Sybil principal、版本轮换、post-commit equivalence、错误或遗漏 lineage、已登记/未登记共同原因、registry 污染、复杂度溢出和 replay 故障。签名与 hash 只证明身份和完整性，不证明观测真实；协议不防御持合法凭证的恶意主体，也不保证错误安全工件、错误 mapping 或遗漏共同原因。

### 3.2 Eventifier 与 identity contract

冻结 Eventifier 按工况阶段、变化点规则和最大持续时间把连续流切成 acquisition epoch。签名 AcquisitionManifest 绑定 Eventifier id/version/hash、可信 clock domain、区间 ([t_{start},t_{end}))、causal boundary、原始采集身份和分段证据；RootIdentityManifest 再绑定其 hash。Eventifier 的粒度不是天然真理，因此 v6.8 把 split/merge refinement 作为压力因子：在不改变底层物理 truth 的情况下改变分段，测量 belief、动作和 false-block 对 root 定义的敏感性。

可信 sequencer 以 ((\tau_k,\mathrm{message\_id})) 形成全序。exact retry 由 canonical root、bundle version 和 envelope hash 的联合键识别；同版本异 payload 是 equivocation，而不是 duplicate。新增 root-equivalence edge 是版本化 control event；若连接了已提交 roots，系统必须从最早受影响 checkpoint 重放。

### 3.3 Root-level mapping 与视图语义

SourceAdapter 把原始观测与质量标记映射为 typed feature、校准证书和 validity status。主路径的 RootLevelMapperManifest 冻结输入 schema、允许 view、联合校准集、适用域、代码/容器 hash 与失败策略，并由同一 sealed bundle 的全部有效 typed features 一次生成 RootClaimBundle (mathcal V_r)。它只允许一次进入全局 belief；各场景边缘只是查询视图。

本文不再宣称“加入任意语义等价 view 后 joint valuation 必然不变”。只有两类可验证情形：

1. exact duplicate、principal alias 或被 canonicalizer 明确消除的冗余 view 不改变输入集合；
2. 新 view 改变 mapper 输入时，它必须形成更高 bundle version，并按 supersede 重编译整个 root，不能作为新的独立 contribution 叠加。

若需要更强的 view-refinement invariance，必须对冻结 mapper 单独证明 idempotence；当前合同不默认该性质。

### 3.4 SafetyArtifactIR、PCR 与 OLR

过程安全前端输出危险场景、动态 demand guard、屏障角色、允许效用族、trace、PCR 与 OLR。FTA/MCS 只提供顶事件结构支持；Bow-Tie 提供路径与屏障角色；LOPA/IPL independence 不等于 evidence distinctness；CCF 参数只进入物理生成模型；HAZOP 提供偏差本体而不自动产生 Eventifier 阈值。每个输入必须被标记为 COMPILED、INTENTIONALLY_UNMAPPED 或 REJECTED，越权推理失败关闭。字段、失败码、完整状态机和 hash 合同见 S2-v20.1。

对候选 root (o)、活动 roots (A_k) 与上下文 (c)，组合只在签名集合级证书

$$
\mathsf{Eligible}(o;A_k,c)=1
$$

时发生。证书必须给出声明图覆盖清单、祖先闭包、高阶超边、已建模物理潜变量和最小见证子图。ELIGIBLE 的语义是“相对于冻结 registry、mapper 与声明完备性合同获得准入”，不是“统计上证明真实独立”。缺元数据、低检验功效、过期 edge、context mismatch 或 coverage gap 均保持 UNKNOWN。v6.8 使用仅 scorer 可见的 oracle graph 注入漏边、伪边、高阶超边遗漏和错误 root merge，量化该条件保证的脆弱性。
"""


OPERATOR = r"""## 4 信念组合专用的 exactly-once 准入语义

### 4.1 准入与提交

设全局 belief 为 (\mathbb B)，候选 root 的唯一 joint valuation 为 (mathcal V_r)。只有身份、mapping、集合资格、预算、速率、冲突和资源门全部通过时，才执行

$$
\mathbb B^+=\operatorname{NormConj}(\mathbb B^-,\mathcal V_r),
$$

并在同一可串行事务中写入 ledger、registry、budget、rate 与 gate state。任一 UNKNOWN 或失败只写具名 audit outcome，不新增 belief contribution。fail-closed 的含义仅是融合服务不得新增 contribution 或输出 SAFE_ELIGIBLE；它不表示物理装置已安全，也不替代 BPCS、SIS、ESD 或人工处置。

算法主链如下，字段级细节由 S2-v20.1 承担。

| 顺序 | 操作 | 不变量/失败语义 |
| --- | --- | --- |
| 1 | 认证 RootIdentityManifest 与 AcquisitionManifest | 身份失败只进 quarantine，不建立 root |
| 2 | 校验 envelope、版本、seal 与 exact retry | 同版本异 payload 拒收；exact retry 幂等 |
| 3 | SourceAdapter 与 root-level mapper | mapping 未知/漂移则不产生 contribution |
| 4 | 解析 root equivalence 与生命周期 | 已见 root 的高版本只走 supersede |
| 5 | 重建 setwise eligibility certificate | coverage 缺口保持 UNKNOWN |
| 6 | 预留 commitment、rate 与资源 | 失败不改变既有 active contribution |
| 7 | 组合并原子提交 (\mathsf X_k) | belief、ledger、budget、gate 同步 |
| 8 | 更新 latch 与 action eligibility | replay stale 或 provenance invalid 禁止 SAFE |

### 4.2 最小反例：为什么 transport exactly-once 不够

在框架 (Theta=\{H,\neg H\}) 上，某次物理采集 (a) 产生简单支持函数

$$m_a(\{H\})=0.80,\qquad m_a(\Theta)=0.20.$$

同一采集经两个 adapter 形成不同消息键 (k_1,k_2)。若 transport 层保证每个键恰好提交一次，但系统暂时把它们登记为不同 roots，则无冲突合取后

$$m_{k_1\oplus k_2}(\{H\})=1-(1-0.80)^2=0.96.$$

unique-root oracle 仍是 0.80。此处没有消息重试：两个键都只处理了一次；也没有必须由冲突检测暴露的异常。后来审计证明 (k_1\sim k_2) 时，普通 idempotency key 只能说明两个事件均已提交，不能把 0.96 自动恢复为 0.80。仅记录 provenance 也不足以规定旧 contribution、预算与动作状态如何撤销。

本文语义把新增等价边视为 control event：收缩等价类，选择 canonical representative，从最早受影响 checkpoint 移除旧 member contributions，用 class-level mapper 生成至多一个 joint contribution，并原子重建 belief、ledger、budget、gate 与 action state。历史 processing charge 可审计且不退款，但当前 epistemic contribution 只能有一个。相同机制用于 version supersession；merge/retire/replay 不能以普通新消息进入组合。

该反例是必要性证明，不是充分的新颖性证明。MME 必须让简单 event-sourced exactly-once baseline、provenance/lineage baseline 和本文方法共同接受相同外部 truth，再比较输出；若基线同样恢复 unique-root oracle，C1 被否证。

### 4.3 生命周期状态转换

每个 root 的 lifecycle 仅取 UNCOMMITTED、ACTIVE、NONCONTRIBUTING、RETIRED 或 MERGED；尝试日志与有效版本分开。核心转换为：

- **INITIALIZE**：从未承诺 root 首次通过所有门后形成一个 active contribution；
- **SUPERSEDE**：更高版本替换同一 root 内容，复用既有 root slot，不增加独立信息量；
- **MERGE**：已确认等价的 roots 收缩为一个 class，删除成员旧 contribution 后重编译；
- **RETIRE**：root 退出活动集合并触发从 checkpoint 的确定性重建；
- **REPLAY**：只消费 FrozenExogenousContext 与 ImmutableChargeFacts，历史内生快照只供审计；
- **SAFE_HALT**：mandatory merge/replay 无法完成时 belief 标记 UNAVAILABLE，禁止继续服务过期状态。

commitment、acceptance-rate token 与当前 contribution 分离：历史实际 processing/commitment charge 不退款，防止通过版本轮换或 merge 逃逸预算；当前 belief 中的 contribution 则必须与 canonical class 一一对应。完整 CAS 读集、tie-break、timer、redirect 和失败码见 S2-v20.1。

### 4.4 行动边界与拒绝成本

SAFE_ELIGIBLE 除 belief 风险外还要求 ISCM 正常且新鲜、provenance verified、replay current、gate accepted、无打开 safety latch，并对全部允许效用满足风险上界与宽度门。UNKNOWN、complexity overflow、mapping invalid 或 registry invariant failure 均不能输出 SAFE。

这种语义天然可能增加 abstention 和 false block。因而“重复贡献减少”不能单独构成系统优越性；必须同时报告良性 SAFE availability、误升级、正确行动延迟、miss mass、P99/OOM 和资源预算。若方法通过拒绝一切获得零 unsafe-SAFE，确认性 no-harm 门会使 C-System 失败。
"""


THEORY = r"""## 5 条件实现性质与支撑性分析

### 5.1 三个实现命题

**命题 1（Exact-duplicate and lifecycle conservation）。** 在身份绑定、root-level mapper、atomic commit 和 canonicalization 成功的执行域内，exact retry、principal alias 与 ledger replay 不增加当前 contribution；supersede 保持 root slot 数不变；merge 后每个 canonical class 至多保留一个 active joint contribution。该命题不声称任意新增 view 都保持 valuation 不变。

**命题 2（Replay/canonicalization equivalence）。** 对相同 FrozenExogenousContext、ImmutableChargeFacts 和全序事件前缀，规范在线执行与从合法 checkpoint 重放得到相同 effective registry、ledger、belief、budget、rate 和 gate state。缺失工件、canonicalization failure 或 cap overflow 进入显式 fail-stop，不属于成功域。

**命题 3（Registry-relative exclusion consistency）。** 若声明的 observation-generation graph、physical-coupling hypergraph、adapter/mapping 和 completeness contract 对目标执行域正确且覆盖充分，则获准组合不会由该声明图中已知的共同祖先或重复路径造成额外 contribution。该命题不是对真实独立性的无条件 soundness；漏边、伪边、错误 root merge 和错误 Eventifier 必须通过 oracle stress test 单独量化。

三个命题是架构/实现性质，而不是新的信念函数定理。S1-v20.1 给出性质测试义务；v6.8 要求独立 oracle 与第二实现进行 differential verification。若任一生命周期轨迹出现 class contribution 大于 1，核心架构直接否证，停止性能实验。

### 5.2 接受分支的支撑性 (1/\delta) 界

对固定操作数 (b)，令 (s_b(q)=1-K_{\mathrm{norm}}(b,q))、(F_b(q)) 为归一合取的接受分支，并定义

$$\mathcal A_{b,\delta}=\{q:s_b(q)\ge\delta\}.$$

在有限框架且 (delta\in(0,1]) 时，跨操作数与接受输入类的 (L_1) 一致 Lipschitz 常数为

$$
L_\delta^\star=
\sup_b\sup_{q\ne q'\in\mathcal A_{b,\delta}}
\frac{\|F_b(q)-F_b(q')\|_1}{\|q-q'\|_1}
=\frac1\delta .
$$

该结果沿用归一合取与随机集交的既有连续性工具 [30], [43]，本文仅把它用于冻结接受轨迹的敏感性审计。它不跨越 hard gate、supersede、merge、retire 或 replay，也不是本文主要理论创新。

若每一步先以单一遗忘率预测，且共同接受步的 survival mass 不低于 (delta_\star)，则目标 root 内容替换导致的轨迹距离可按接受次数与遗忘时间形成上界；详细式与证明义务保留在 S1-v20.1。每个候选必须重新检查 gate margin，不能把一个时刻的界外推为未来安全证书。

### 5.3 保证边界与敏感性义务

实现命题依赖四个外部对象：Eventifier、root-equivalence evidence、registry coverage 和 root-level mapper。v6.8 为每个对象规定否证压力：

1. 对同一 latent physical truth 改变 Eventifier split/merge 粒度；
2. 随机删除/添加 lineage edge 与高阶 hyperedge；
3. 延迟 root-equivalence disclosure，覆盖 post-commit merge；
4. 加入不增加信息的 views 与真正独立 roots，分别测量不变性和响应性；
5. 使用独立实现和 scorer-only oracle，禁止从本文 ledger 读取真值。

只有在这些压力下同时保持 unique-root oracle 一致性和合理 availability，才能把“合同一致”升级为可发表的机制证据。
"""


VALIDATION = r"""## 6 验证状态与分阶段实验设计

### 6.1 SHK-000：非确认性工程资格，而非论文结果

远程 SHK-000 已在实际 NVIDIA L20 主机上完成窄资格：25 项工程测试通过，16/16 canary 检查通过；100 个 physical seed 产生 100 个不同 truth hash，固定 physical seed 的 10 个 noise seed 保持 1 个 truth hash并产生 10 个 evidence hash；重复运行保持 hash 一致。该结果只支持 toy generator 的 seed/hash 隔离和一小部分 duplicate/root contract。

同一次执行的 G0_RESOURCE 失败，完整 G1/G2/P0 未关闭，`PILOT_AUTHORIZED=false`、`D_TEST_AUTHORIZED=false`，权威结果标记 `claim_support=none`。它没有验证完整 supersede/merge/retire/replay、第二实现、物理 ACL 隔离、MME、功效、系统优越性或外部效度。本文因此把 SHK-000 作为工程状态披露，不把它写入 abstract 的效果结论。

### 6.2 Phase 1：外部 oracle 驱动的最小机制实验

MME 是投稿前最低证据，不使用确认性 `D_test`，也不能用于调 SESOI、no-harm margin 或效应方向。scorer-only oracle 保存 latent physical-acquisition id、真实 ancestry graph、真实独立 root 与 action-relevant state；所有方法只见相同的 opaque events。

比较方法至少包括：完整方法 A；简单 event-sourced exactly-once baseline；provenance/lineage-only baseline（含 PRIMEX-PEV 型逻辑）；cautious/partial-dependence baseline；naïve normalized-conjunctive reference。四类操纵为 exact retry、不同键同源 views、延迟披露的 post-commit equivalence、真正独立的新 root；另对 registry 漏边/伪边、高阶边遗漏和 Eventifier split/merge 做压力测试。

对方法 (m) 的公共输出 (g_m) 定义冗余扰动不变性

$$
DRI_m(k)=d\{g_m(X\cup D_k),g_m(X)\},
$$

其中 (D_k) 只增加重复或派生 views；并定义独立信息响应

$$
SRI_m(k)=d\{g_m(X\cup I_k),g_m(X)\},
$$

其中 (I_k) 增加 oracle 证明独立的新采集。理想方法对 (D_k) 的 DRI 小，但对有决策意义的 (I_k) 仍有足够 SRI。主要评分统一使用 belief/credal-risk/action 输出与 unique-root oracle 的距离；A 的内部 canonical-root count 只作诊断，不能当裁判。

MME 同时报告 duplicate suppression、post-merge recovery error、false block、benign availability、wrong-direction action、decision delay、P99、OOM/crash 和 replay cost。若 A 只降低 DRI 却显著压低 SRI 或 availability，不能进入确认性主张。

### 6.3 Phase 2：门控确认性设计

目标总体仍限定为两个预签、结构不同的 barrier-explicit exothermic CSTR strata；它们是固定验证层，不代表从“拓扑总体”随机抽样。每个 topology 分别报告效应和交互，混合 estimand 使用预签权重。只有未来从冻结 topology generator 独立抽取足够多结构并设置 held-out family，才允许随机效应或拓扑总体外推。

主比较为 A 对在独立 `D_select` 上按冻结规则选出的唯一 G*；每个功效 Monte Carlo replicate 重做选择。三个固定 sentinel baselines 进行 Holm 调整的支持性比较，用于检验 G* 脆弱性。winner stability 未过门时当前版本停止并升版，不在同一协议临时换 baseline。

共同主终点保留：(i) unsafe-SAFE 或方法失败的复合风险，且两个组件各自 no-harm；(ii) restricted correct-action delay。良性 SAFE availability、miss mass、误升级、拒判、barrier calibration、P99 和资源合同为绑定资格门。正确行动由独立安全团队在 test 生成前双签 `ActionTruthRuleManifest`、generator/scorer code 与 hash；bundle manifest 自动生成，执行 100% 机器资格和预签分层人工抽审，禁止逐 bundle 人工编辑。

### 6.4 IUT、联合功效与预算可行性

系统通过事件是全部共同主效应和资格门的交集

$$
\pi_{joint}=P\!\left(\bigcap_j E_j\right),
$$

不能用边际功效的乘积近似，除非通过事件独立。IUT 的复合零假设中只要至少一个组件为真，全部拒绝的概率即由单个组件的单侧 (alpha=0.025) 控制；不在 IUT 组件间再做 Bonferroni 拆分。v6.8 使用完整 joint endpoint kernel，对相关终点、batch ICC、failure、miss mass、G* 选择和所有 gate 进行联合 Monte Carlo，并用独立 power-confirm seed 复核一次。

新增预算硬门：若在冻结 nuisance grid 上不存在 (n\le n_{max,budget}) 使完整 gate 的功效下限达到目标，则 `C-System=NOT_TESTED`，不得生成 `D_test`。pilot 后不能在原协议删除终点以追求阳性；只能停止、升版并用独立数据验证较弱主张。

### 6.5 Phase 3：外部支持与措辞纪律

同一数值生态的两个 CSTR 只支持有限模拟域。投稿前至少需要独立 simulator、shadow 或 HIL 中一项，且复用冻结的 root/registry/oracle 接口。HRI/6M 可作为未来异构 transportability case，但 6M 分类不是方法创新，也不能替代 lifecycle MME。

结果措辞按门降级：只有性质资格成功时可声称合同一致；MME 成功可声称相对简单 exactly-once/lineage baseline 的机制增量；确认性 gate 全部通过才可声称系统收益；外部支持未完成时题名、摘要和结论不得外推到通用工业或人机协作。
"""


DISCUSSION = r"""## 7 讨论

本文最强也最容易被攻击的主张是：把 exactly-once 从消息处理边界推进到信念组合的认知贡献边界，并处理提交后才出现的 root equivalence。它不是新组合规则，也不是 provenance 或 event sourcing 的首创。其发表价值取决于一个直接对撞：在相同外部 physical-acquisition oracle 下，普通 transport exactly-once、provenance/lineage-only 和依赖组合基线是否仍偏离 unique-root belief 或动作，而本文能否在不过度拒绝的前提下恢复一致。

过程安全是高约束验证案例而非原创性的唯一来源。SafetyArtifactIR 帮助把 demand、barrier、CCF、lineage 与 forbidden inference 分开，但其字段和失败码不应淹没主线，因此 v21 将大部分规范下沉 S2-v20.1。若 C-HB 消融不通过，过程安全只能保留为应用域；若 lifecycle MME 不通过，即使安全工件编译正确，融合创新也不成立。

条件保证还有四个硬边界。第一，registry-relative 不是现实完备；隐藏漏边必须测。第二，Eventifier 决定 root 粒度，必须做 refinement sensitivity。第三，root-level mapper 对新增 view 未必幂等，不能泛化宣称 view invariance。第四，fail-closed 会牺牲 availability，必须用独立信息响应、false block、正确行动和资源 no-harm 共同约束。

当前稿仍不是可直接投稿的结果论文。SHK-000 证明代码从纯规范进入窄工程资格，但不能回答 Information Fusion 作者指南要求的主要结果、比较证据和标准验证。真正改变编辑结论的节点是：完整生命周期 runtime、独立 oracle/第二实现、MME 对近邻基线的机制优势，以及至少一个受控确认性或外部支持结果。
"""


CLOSING = r"""## 8 结论

本文提出谱系依赖信念融合的生命周期一致组合前治理。其核心不是 provenance、去重或 Dempster 组合本身，而是 evidence-specific exactly-once admission semantics：每个 physical-acquisition root 在非幂等组合中至多形成一个当前认知贡献，并在 post-commit equivalence、supersede、merge、retire 与 replay 中原子重建 belief、ledger、budget、availability 和 action eligibility。

最小反例说明 transport exactly-once 不能自动阻止不同消息键造成的 epistemic double counting。本文给出的保证严格限定为 registry、Eventifier 与 mapper 正确且覆盖充分的执行域；接受分支 (1/\delta) 界只是支撑分析。当前证据仅到窄工程资格，尚无性能或安全收益结论。v6.8 已把独立 oracle MME、完整联合功效、availability/no-harm 与外部支持设为投稿前硬门；任何未过门的主张必须删除或降级。

## 数据与代码可用性

工作区已存在与 v20.1/v6.7 部分合同对齐的 `risk-fusion-bench` 资格切片，以及 SHK-000 的测试、canary、环境和审计工件；该切片只覆盖 seed/hash 隔离、候选完整性和部分 root/ledger 性质。完整 supersede/merge/retire/replay runtime、第二实现、MME、确认性数据和公共匿名复现包尚未完成。投稿前将公开 schema/compiler、状态机、性质测试、生成器、容器、分析代码、冻结 manifests 与可复现工件；当前版本不宣称已有公开数据集结果或完整 reference implementation。

## 伦理与安全声明

过程仿真和公开数据回放不得直接控制 BPCS、SIS、联锁、ESD、紧停或人员保护。IndependentSafetyChainMirror 只读记录外部状态。任何 shadow/HIL 或人机协作研究必须另行完成伦理、HAZOP/作业安全分析、数据保护和独立安全监护。

## 生成式 AI 使用说明

During the preparation of this work the authors used OpenAI Codex to support literature organization, version comparison, language revision, and consistency checks. The authors reviewed and edited all outputs, verified the cited sources, formulas, code, and final statements, and take full responsibility for the content of the manuscript.

"""


PLAN = r"""# 实验设计与执行计划 v6.8：机制先行、外部 Oracle 与表示中立验证蓝图

> **版本性质：新的候选执行蓝图；不回写 v6.7，不把 SHK-000 晋级为论文证据。** v6.8 引入 Phase 1 MME、registry/Eventifier 错设压力、固定 sentinel baselines、预算可行性门和规则级 ActionTruth 双签。任何 `D_test` 活动仍未授权。

## 0 当前状态与硬边界

| 项目 | 状态 | 含义 |
| --- | --- | --- |
| SHK-000 | 25 tests PASS；16/16 narrow canary PASS | 仅工程资格 |
| G0_RESOURCE | FAIL | 不允许完整 pilot/confirmatory |
| 完整 G1/G2/P0 | NOT CLOSED | 生命周期 runtime、第二实现和物理隔离仍缺 |
| PILOT_AUTHORIZED | false | 不得把 canary 迁移为 pilot |
| D_TEST_AUTHORIZED | false | 不生成、不读取、不复制、不重命名 `D_test` |
| claim_support | none | 不支持论文效果结论 |

v6.8 的目标不是提高“阳性概率”，而是尽早判断核心创新是否只是 event sourcing/provenance 的重新包装。只有表示中立 MME 证明近邻基线解决不了 post-commit epistemic equivalence，才投入昂贵确认性试验。

## 1 主张—证据—停止规则

| 主张 | 最低证据 | 通过门 | 失败处理 |
| --- | --- | --- | --- |
| Q1 Lifecycle conservation | 独立 oracle + 第二实现 + exhaustive/property lifecycle traces | 每个 canonical class 当前 contribution ≤1；online=replay | 核心否证，停止全部性能试验 |
| Q2 Registry-relative exclusion | 完整声明图与 scorer-only truth graph 的 stress test | 漏边/伪边曲线、coverage 与 false-link 透明报告 | 降级为声明图 conformance，不声称真实依赖治理 |
| M1 Fusion-specific increment | A 对 simple exactly-once、lineage-only、partial/cautious 的 MME | DRI/recovery 改善且 SRI/availability 不劣 | 停止 IF 主线或重定义问题 |
| C-System | 完整确认性 IUT + 全 no-harm/资源门 | 全部共同主效应与 gate 通过 | 仅描述，不声称系统优越 |
| C-HB | A 对匹配 `A^-Topo` | 预签增量与 no-harm 通过 | 过程安全仅保留应用域 |
| External support | 独立 simulator/shadow/HIL | 预签 transportability 指标通过 | 效力域限于两 CSTR strata |

## 2 数据分区、权限与 oracle 隔离

### 2.1 分区

- `D_impl_unit`：开发测试，不进入论文统计；
- `D_mapper_cal` / `D_mapper_qual`：root-level mapper 校准与资格，互不重叠；
- `D_mme`：非确认性机制实验，可公开但不得调确认性 SESOI；
- `D_select`：G* 选择和 nuisance 估计；
- `D_pilot`：仅在 G0–G3 全部关闭后生成；
- `D_test`：最终确认性密封分区，当前禁止生成。

physical seed 是独立单位；noise、arrival、method、attack、emitter 和 algorithm seed 全部嵌套。TruthManifest、OperationalSafetyArtifact 与 EvaluationManifest 分离。方法只见 opaque token；scorer-only oracle 保存 physical acquisition id、真实 ancestry、CCF 激活和 action state。

### 2.2 Oracle graph

每个 base run 生成两张图：方法可见的 declared graph (G_D) 与仅 scorer 可见的 truth graph (G_T)。压力因子包括：随机漏边、伪边、高阶 hyperedge 遗漏、错误 root split、错误 root merge、延迟 disclosure、过期 edge 和 context mismatch。报告 registry coverage、false-link rate、class reconstruction error 及其对 belief/action 的剂量反应。

## 3 Phase 0：参考实现与资格门

### 3.1 必做实现

1. 完整 INITIALIZE、SUPERSEDE、MERGE、RETIRE、REPLAY、SAFE_HALT 状态机；
2. root-level mapper 与 versioned bundle replacement；
3. Atomic ledger/budget/gate/action transaction；
4. scorer-only oracle 与独立第二实现；
5. property-based lifecycle trace generator；
6. physical truth 与 operational payload 的权限负测；
7. crash/restart、CAS retry、乱序和 cap overflow 注入。

### 3.2 Phase 0 通过门

- exact retry、alias 和 replay 不增加 contribution；
- post-commit merge 恢复 unique-root oracle；
- online 与 checkpoint replay bitwise/semantic equivalent；
- mandatory rebuild 失败进入 UNAVAILABLE/SAFE_HALT，不继续服务旧 belief；
- 第二实现与主实现对冻结 trace differential agreement 100%；
- credential、truth path、candidate write 与 `D_test` namespace 审计均为零违规；
- `pip check`、unit/property/integration、reproducibility 和 artifact hash 全通过。

任一核心 invariant 失败即停止，不得以“实现缺陷与理论无关”为由继续性能试验。

## 4 Phase 1：Minimal Mechanism Experiment

### 4.1 方法面板

- A：完整生命周期组合前治理；
- B0：naïve normalized conjunctive；
- B1：simple event-sourced exactly-once，仅以消息 id/version 去重；
- B2：provenance/lineage-only，尽量复现 PRIMEX-PEV/祖先删除语义；
- B3：cautious rule；
- B4：partial-dependence/ER-TLD 型强近邻；
- B5：unknown-correlation conservative baseline（适用公共输出时）。

所有方法读取同一事件流、资源 cap、deadline 与 action schema；不得让 A 独享 truth 或更宽资源。

### 4.2 操纵矩阵

| 因子 | 水平 | 目的 |
| --- | --- | --- |
| duplicate class | exact retry / distinct-key same acquisition / derived view | 区分 transport 与 epistemic duplicate |
| equivalence timing | pre-commit / post-commit short / post-commit long | 检验 rollback/rebuild |
| lifecycle | supersede / merge / retire / replay combinations | 覆盖核心状态机 |
| independent information | 0 / 1 / multiple new roots | 防止“拒绝一切” |
| registry error | missing / spurious / missing hyperedge / wrong merge | 测条件保证脆弱性 |
| Eventifier | reference / over-split / over-merge | 测 root 粒度敏感性 |
| conflict | low / directional / high | 避免只在无冲突例中获益 |
| load | nominal / cap-near / overflow | 检验 fail-stop 与资源成本 |

MME cell 数在实现完成后由 pairwise coverage 与边界覆盖确定，不使用“至少 5–6 个拓扑”这类无统计依据的常数。MME 的 replicate 用于机制曲线和不确定性区间，不作为确认性功效承诺。

### 4.3 公共指标

设 (D_k) 为不增加新物理信息的重复/派生 views，(I_k) 为 oracle 证明独立的新 roots：

$$DRI_m(k)=d\{g_m(X\cup D_k),g_m(X)\},$$

$$SRI_m(k)=d\{g_m(X\cup I_k),g_m(X)\}.$$

主评分尺度：与 unique-root oracle 的 belief (L_1)/Jousselme distance、credal risk deviation、action-set disagreement、post-merge recovery error。约束指标：SRI、benign availability、false block、wrong-direction action、restricted delay、P99、memory、replay cost、crash/OOM。A 的 internal ledger count 只作 debug，不进入主要比较。

### 4.4 MME 晋级门

A 必须在 post-commit distinct-key duplicate 上相对 B1/B2 显著降低 oracle deviation，并在独立信息条件下保持预签 SRI、availability、delay 和资源 no-harm。若效应仅存在于 A 自己定义的 root count，或只靠更高 abstention 获得，M1 失败。

## 5 Phase 2：确认性试验

### 5.1 目标总体与拓扑

两个 barrier-explicit exothermic CSTR 是固定 scientific strata；目标只覆盖预签加权混合。每拓扑分别报告主效应与 topology×method interaction。不得把两个拓扑称为随机抽取的拓扑总体。未来若要随机效应，必须有冻结 topology generator、独立抽样、足够 cluster 和 held-out family。

### 5.2 G* 与稳健性基线

G* 在独立 `D_select` 上按冻结 loss、service constraints 与 tie-break 选择；确认分析条件化于唯一 G*。每个 power replicate 重做完整选择。另固定三个 sentinel baselines，作 Holm 调整的支持性比较。winner stability 未达到预签阈值时，当前版本停止并升版；不得在 test 后改 G*。

### 5.3 终点与 IUT

共同主终点：

1. (Y^{UF}=I(Y^{US}\lor Y^F))，同时对 unsafe-SAFE 与方法失败分别设 no-harm；
2. restricted correct-action delay，错误方向、超时、no-action 和窗内失败均不能完成终点。

绑定门包括 benign SAFE availability、miss mass、误升级、拒判、barrier calibration、demand sensitivity、P99、memory/OOM、update/query budget 和 SAFE invariant。通过事件为所有事件交集；不把边际功效相乘。

### 5.4 ActionTruth

独立过程安全团队在任何 test seed 前双签 `ActionTruthRuleManifest`、允许集合、deadline、generator/scorer code/hash 和分歧规则。每个 bundle 的 manifest 由冻结规则自动生成；执行 100% 机器资格和按 severity×topology×path 分层的预签人工抽审。禁止逐 bundle 人工改标签，也禁止看方法输出后修订。

## 6 功效、样本量与预算门

联合 kernel 同时模拟 paired binary table、delay/miss mass、跨终点相关、batch ICC、失败率、CCF 权重、G* 选择和所有资格门。每个 Monte Carlo replicate 执行完整 pipeline；独立 power-confirm seed 只复核一次。

IUT 的各单侧组件使用 (alpha=0.025)，不再对 IUT 组件做 Bonferroni 拆分。支持性 sentinel 比较使用 Holm。若 nuisance 依据不足，先报告 MDE/power surface，不猜正向效应。

预算门：在冻结 nuisance grid 上必须存在 (n\le n_{max,budget}) 使 joint pass probability 下限达到目标；否则 `C-System=NOT_TESTED`，不生成 `D_test`。pilot 后若失败，只能停止、升版和独立确认，不能删终点或放宽 no-harm margin。

## 7 资源与执行顺序

远端实际 GPU 为 L20，但当前共享负载高且存储自由空间低于 G0 阈值。执行顺序：

1. 清理或扩容后重新签署 server profile；
2. 闭合真实 G1 生成器资格与物理/权限隔离；
3. 闭合完整 G2/P0 生命周期 runtime 与第二实现；
4. 运行 Phase 1 MME，输出独立 verdict；
5. 只有 M1 通过才准备 G3/power/pilot；
6. pilot 成功且所有 manifest/hash/ACL 通过后，才讨论 `D_test` 授权。

任何输出路径非空、出现 `D_test` 字样、candidate 可写、truth 可被方法读取、磁盘/内存不足、未分类系统失败或资源日志缺失均立即退出。

## 8 产出清单

- `Phase0QualificationManifest.json` 与第二实现 differential report；
- `MMEPreregistration.json`、oracle truth hash、公共 event bundles；
- DRI/SRI、oracle deviation、availability/action/resource tables；
- registry/Eventifier stress curves；
- `GStarSelectionManifest.json` 与 winner-stability report；
- `JointPowerSurface.json`、独立 power-confirm report；
- `ActionTruthRuleManifest.json` 与自动 bundle audit；
- 完整 provenance、environment freeze、container digest、seed tree 和 run manifest；
- 一份明确的 GO/NO-GO 编辑结论，不用“趋势良好”替代门。
"""


REPORT = r"""# 研判报告二十四：报告二十三裁决、v21 重构与 Information Fusion 创新性论证

## 一、执行结论

**报告二十三有价值，但不能整包采纳。** 它准确抓住了四个会导致 *Information Fusion* 拒稿的问题：正文规格书化、实现/证据不足、评价口径可能偏向 A、以及在昂贵确认性试验前缺少低成本机制去风险。它同时包含五个应明确拒绝的判断：把联合功效近似为边际功效连乘、认为 5–6 个拓扑即可合理使用随机效应、主张 G* 应直接删除、用乘法 composite 合并安全与 availability、以及把 HRI/6M 或 operator-agnostic 扩张当成自动提高创新性的路线。

v21 已据此完成实质重构：不再以“动态过程安全 + provenance + ledger”的组件拼装论证创新，而把主张收敛为**非幂等 belief fusion 中、面向证据贡献的 exactly-once 生命周期语义**。新增了普通 transport exactly-once 无法修复的数值反例；弱化了过强的 view invariance 和 registry soundness；把 (1/\delta) 降为支撑分析；加入 SHK-000 的非确认性边界；并把 MME、外部 oracle、registry/Eventifier 错设和完整联合功效写入 v6.8。

不留情面的结论仍是：**v21 比 v20.1 更像 Information Fusion 论文，但现在仍不应投稿。** 当前最大风险已从“没有清晰创新核”降为“创新核有可证伪定义，但没有足够机制证据”。只有完整生命周期 runtime、独立 oracle/第二实现和至少一个相对强近邻的 MME 通过，EIC 结论才可能从 Premature Reject 变成可外审。

## 二、报告二十三逐项裁决

| 编号 | 裁决 | 有价值的部分 | 必须纠正的部分 | v21/v6.8 处理 |
| --- | --- | --- | --- | --- |
| P-A1 防守性收窄导致创新不足 | 部分采纳 | 组件都已有近邻，必须证明非显然组合 | IF 官方范围明确接受 architecture；没有新 fusion rule 不等于无创新 | 用 fusion-specific lifecycle semantics + 最小反例重写主线 |
| P-A2 丢失 HRI/6M 差异化 | 不采纳为主线 | 异构人机数据可做未来外部支持 | HRI 不是蓝海，6M 分类不是方法创新；回切会造成 scope drift | 过程安全保留高约束案例，HRI 仅列未来 transportability |
| P-A3 试验大概率零结果 | 部分采纳 | 应先用 MME 判断核心机制是否成立 | strict gate 防止用 abstention 换安全，不是“注定失败” | 新增 Phase 1 MME；不过门不进入 confirmatory |
| P-B1 (1/\delta) 理论弱 | 采纳其 novelty 判断 | 不足以承担标题级理论创新 | 该界仍可作轨迹敏感性工具 | v21 明确“沿用工具、支撑分析” |
| P-B2 相对 soundness 循环 | 部分采纳 | registry completeness 在部署时不可直接观测 | 条件命题逻辑上不循环，只是经验内容弱 | 改名 registry-relative exclusion consistency + oracle 错设曲线 |
| P-C1 两拓扑不足 | 部分采纳 | 不能支持拓扑总体外推 | “至少 5–6 个拓扑即可随机效应”无依据且 cluster 太少 | 明确固定 strata；未来需冻结 generator、独立抽样、held-out family |
| P-C2 IUT × 多门功效黑洞 | 关注点采纳，论证驳回 | joint pass probability 必须硬评估 | 联合功效一般不等于边际功效连乘；IUT 组件也无需 Bonferroni 拆分 | 保留完整 joint-kernel Monte Carlo 与预算可行性门 |
| P-C3 G* 脆弱 | 部分采纳 | winner stability 必须报告 | 独立 `D_select`、test 前冻结、每个 power replicate 重选可辩护 | 保留 G*；增加 3 个 fixed sentinel + Holm；不稳定则升版停止 |
| P-C4 ActionTruth 人工瓶颈 | 采纳 | 逐 bundle 双签不可扩展 | 不能因此放弃独立真值 | 改为规则/代码/hash 双签 + 自动 manifest + 分层人工抽审 |
| P-C5 实现不存在 | 已部分过时 | 完整 lifecycle、第二实现和物理隔离仍缺 | SHK-000 已有 25 tests 与窄 canary，不再是“只有玩具 9 测试” | 如实写入工程资格，明确 `claim_support=none` |
| P-C6 评价偏向 A | 采纳，且报告方案仍不够 | 必须使用表示中立外部真值 | “canonical root 有效次数”若读取 A ledger 仍偏向 A | 用 scorer-only physical acquisition/ancestry oracle 与公共输出尺度 |
| P-D 投稿形态 | 基本全采纳 | 规格过密、50 refs 上限、可用性声明不合投稿 | 不能靠语言润色解决缺结果 | 主文瘦身；保持 50 refs；更新 partial implementation 声明 |
| 路线 3 operator-agnostic | 当前拒绝 | 长期可能扩大意义 | 现理论和实现绑定 belief functions/normalized conjunctive | v21 不作 operator-agnostic 声明 |

## 三、报告二十三的关键统计错误

第一，全部 gate 的通过概率是

$$\pi_{joint}=P\left(\bigcap_jE_j\right),$$

不是 (prod_jP(E_j))，除非事件独立。多个 endpoint、failure、availability 和 G* 选择高度相关，用连乘会给出虚假的“功效黑洞”印象。正确做法是 v6.8 的完整 joint endpoint kernel，对每个 Monte Carlo replicate 重跑选择、推断和所有 gate。

第二，IUT 不需要把 (alpha) 在组件间 Bonferroni 拆分。复合零假设中只要至少一个组件零假设为真，全部拒绝的概率就不超过该组件的检验水平。支持性多 baseline 比较才使用 Holm。

第三，把 unsafe-SAFE/方法失败与 availability/latency 做乘法 composite 会混合单位、隐藏驱动因素并允许权重操纵。保留共同主终点与显式 no-harm 门更透明。

第四，pilot 后若预算内功效不足，不能在同一协议删除终点“回退”。只能停止、升版、弱化主张并用独立数据确认。

## 四、当前创新性能否成立

### 4.1 可成立的最窄创新陈述

> 对非幂等信念组合，定义 evidence-specific exactly-once admission semantics：当 root 在提交后发生 equivalence、version replacement、merge、retire 或 replay 时，使 epistemic contribution、commitment budget、belief availability 与 safety-action eligibility 在同一原子事务中重建，并把真实独立性主张严格限定为 registry/Eventifier/mapper 正确且覆盖充分的执行域。

这比“provenance-aware once-only fusion”更窄也更可检验。Kowalski 与 Martin 已讨论 belief-function combination 的 provenance；Yu 等已用 provenance 避免 DS trust 中 double counting；PRIMEX-PEV 已编码信息谱系并消除冗余祖先。因此，只有“post-commit lifecycle transaction 对非幂等 belief contribution 的额外必要性”可能是原创核，而 provenance、lineage 或 duplicate removal 本身不是。

### 4.2 最小反例为何重要

同一采集形成两个不同传输键，各自满足 transport exactly-once；两个 (m(\{H\})=0.8,m(\Theta)=0.2) 的简单支持合取后变为 0.96，而 unique-root oracle 是 0.80。事后发现 root equivalence 时，消息去重无法撤销已进入 belief 的第二份贡献。该反例把“这是 event sourcing 换名”的争论变成可实验问题：simple event-sourced baseline 若能同样恢复 0.80，核心创新被否证；若只能本文的 lifecycle transaction 同时恢复 belief、budget 和 action，创新获得直接证据。

### 4.3 目前仍缺什么

- 完整 INITIALIZE/SUPERSEDE/MERGE/RETIRE/REPLAY/SAFE_HALT runtime；
- 独立第二实现或 oracle，而不是由 A 的 ledger 自证；
- simple exactly-once、Yu/Kowalski/PRIMEX 型 lineage baseline 和 partial/cautious 强近邻；
- post-commit equivalence、hidden registry omission、Eventifier refinement 和真正独立信息响应；
- belief/decision consequences 与 availability/resource no-harm；
- 至少一项独立 simulator、shadow 或 HIL 外部支持。

在这些缺失关闭前，创新性只能写成“plausible and falsifiable”，不能写成“demonstrated”。

## 五、Information Fusion 投稿适配

*Information Fusion* 官方范围明确接受 information fusion 的 architecture、algorithms 与 applications，因此架构稿并非天然低一等；本项目的 topic fit 是高的。真正的拒稿风险是 Research Article 没有足以支撑 main claim 的结果。官方作者指南还要求 10–35 页、最多 50 篇参考文献，并在 cover letter 中回答 SOTA、公共数据、标准验证、main claim、主要结果/证据和 closest work。v20.1 正好 50 篇，v21 通过替换而非新增纳入 provenance-aware double-counting 与 stream exactly-once 近邻。

当前编辑判断：

| 维度 | v20.1 | v21 | 投稿前最低状态 |
| --- | --- | --- | --- |
| Journal fit | 高 | 高 | 保持 |
| 原创核 | 被规格淹没、容易被视为拼装 | 已形成 fusion-specific lifecycle 反例与主张 | MME 对强近邻通过 |
| 理论 | (1/\delta) 被抬得过高 | 已降为支撑分析 | 不再过度包装 |
| 实现 | 文本强、runtime 弱 | 窄资格已披露 | 完整 lifecycle + 第二实现 |
| 实验 | 确认性方案很大 | MME→confirmatory 分层 | MME 先过门；joint power 可行 |
| 投稿形态 | spec-heavy | 主文问题化、字段下沉 | 结果替换设计陈述；Word 页数核验 |
| 当前决定 | Premature reject | 仍是 Premature，但可救 | 完成最低证据后再判断送审 |

## 六、SHK-000 的真实价值

可以写入工程记录：实际 L20 已识别；25 项测试通过；16/16 窄 canary 通过；toy generator 的 physical/noise seed 与 truth/payload hash 机制可复现；candidate 与 `D_test` 边界审计无违规。

不能写成论文结果：G0_RESOURCE 失败；完整 G1/G2/P0 未关闭；pilot 与 `D_test` 未授权；无完整 lifecycle、第二实现、物理隔离、MME、power 或系统对比。v21 只在“验证状态”中披露，摘要不宣称效果。

## 七、v21 与 v6.8 已完成的改进

1. 题名从“动态过程安全的组件链”改为“谱系依赖信念融合的生命周期一致语义”；
2. 新增 transport exactly-once 与 epistemic exactly-once 的数值反例；
3. 把任意 view invariance 弱化为 exact duplicate invariance + versioned root recompilation；
4. 把 Setwise Eligibility Relative Soundness 改为 Registry-relative Exclusion Consistency；
5. 把 (1/\delta) 明确为沿用的支撑工具；
6. 将字段、路由和失败码移交 S2-v20.1，主文保留核心状态和反例；
7. 用 Yu et al. 2008 替换边缘社会技术引用，用 Dataflow exactly-once 近邻替换一条次要 HAZOP 引用，仍保持 50 篇；
8. 新增 external-oracle MME、DRI/SRI、registry/Eventifier stress 和 simple exactly-once baseline；
9. 保留可辩护的 G*，增加 fixed sentinels、Holm 与 winner-stability stop；
10. 新增预算可行性门、规则级 ActionTruth 双签和自动 bundle audit；
11. 如实更新数据/代码可用性：有 partial qualification slice，无完整 reference implementation；
12. S1/S2-v20.1 未被无声改写；需要改变规范语义时必须另行升版。

## 八、最终建议

现在不要向 *Information Fusion* 投稿，也不要继续堆正文规范。下一投入顺序应是：完整生命周期 runtime → 独立 oracle/第二实现 → Phase 1 MME → 编辑 GO/NO-GO → 资源与 joint power gate → pilot/confirmatory → 外部支持。若 MME 不能证明 simple exactly-once/lineage-only 的不足，应及时停止当前创新叙事，而不是用更多 CSTR cell 掩盖核心问题。

证据入口：[*Information Fusion* journal scope](https://www.sciencedirect.com/journal/information-fusion)；[Guide for Authors](https://www.sciencedirect.com/journal/information-fusion/publish/guide-for-authors)；[Kowalski & Martin 2018](https://doi.org/10.23919/ICIF.2018.8455764)；[Yu et al. 2008](https://doi.org/10.1109/CTS.2008.4543955)；[PRIMEX-PEV](https://isif.org/media/encoding-information-lineage-scalable-distributed-fusion)；[Information Fusion 中的 HRC 异构融合近邻](https://doi.org/10.1016/j.inffus.2024.102717)。最后一项说明 HRI/HRC 已有直接同刊工作，不能把“回切 HRI”当成无竞争蓝海。
"""


def build_main() -> str:
    text = SOURCE.read_text(encoding="utf-8")
    text = replace_section(text, "# ", "## 符号与缩略语", HEADER)
    text = replace_section(text, "## 符号与缩略语", "## 1 引言", SYMBOLS)
    text = replace_section(text, "## 1 引言", "## 2 相关工作与研究定位", INTRO)
    text = replace_section(text, "## 2 相关工作与研究定位", "## 3 生产安全状态、可信时间与证据包", RELATED)
    text = replace_section(text, "## 3 生产安全状态、可信时间与证据包", "## 4 溯源约束融合算子", METHOD)
    text = replace_section(text, "## 4 溯源约束融合算子", "## 5 条件实现性质与支撑性理论", OPERATOR)
    text = replace_section(text, "## 5 条件实现性质与支撑性理论", "## 6 确认性验证设计（尚未执行）", THEORY)
    text = replace_section(text, "## 6 确认性验证设计（尚未执行）", "## 7 讨论", VALIDATION)
    text = replace_section(text, "## 7 讨论", "## 8 结论", DISCUSSION)
    text = replace_section(text, "## 8 结论", "## 参考文献", CLOSING)

    old_26 = "[26] M. Delikhoon, E. Habibi, E. Zarei, O.A. Valdez Banda, M. Faridan, Towards decision-making support for complex socio-technical system safety assessment: A hybrid model combining FRAM and dynamic Bayesian networks, Process Saf. Environ. Prot. 187 (2024) 776–791. https://doi.org/10.1016/j.psep.2024.04.147."
    new_26 = "[26] B. Yu, S. Kallurkar, R. Flo, A Dempster-Shafer approach to provenance-aware trust assessment, Proc. 2008 Int. Symp. Collaborative Technologies and Systems (CTS), IEEE, 2008, 383–390. https://doi.org/10.1109/CTS.2008.4543955."
    old_45 = "[45] Z. Li, J. Zhao, HAZOPCT: A HAZOP analysis completeness tool based on knowledge graph reasoning, Process Saf. Environ. Prot. 197 (2025) 107025. https://doi.org/10.1016/j.psep.2025.107025."
    new_45 = "[45] T. Akidau, R. Bradshaw, C. Chambers, S. Chernyak, R.J. Fernández-Moctezuma, R. Lax, S. McVeety, D. Mills, F. Perry, E. Schmidt, S. Whittle, The Dataflow Model: A practical approach to balancing correctness, latency, and cost in massive-scale, unbounded, out-of-order data processing, Proc. VLDB Endow. 8(12) (2015) 1792–1803. https://doi.org/10.14778/2824032.2824076."
    if old_26 not in text or old_45 not in text:
        raise AssertionError("reference replacement anchor missing")
    text = text.replace(old_26, new_26).replace(old_45, new_45)
    return text


def validate_text(name: str, text: str) -> None:
    if "\x00" in text:
        raise AssertionError(f"{name}: NUL found")
    fences = text.count("```")
    if fences % 2:
        raise AssertionError(f"{name}: unbalanced fences")
    if not text.endswith("\n"):
        raise AssertionError(f"{name}: missing final newline")


def main() -> None:
    main_text = build_main().rstrip() + "\n"
    plan_text = PLAN.rstrip() + "\n"
    report_text = REPORT.rstrip() + "\n"
    validate_text(MAIN_OUT.name, main_text)
    validate_text(PLAN_OUT.name, plan_text)
    validate_text(REPORT_OUT.name, report_text)
    MAIN_OUT.write_text(main_text, encoding="utf-8")
    PLAN_OUT.write_text(plan_text, encoding="utf-8")
    REPORT_OUT.write_text(report_text, encoding="utf-8")

    refs = [int(x) for x in re.findall(r"(?m)^\[(\d+)\] ", main_text)]
    if refs != list(range(1, 51)):
        raise AssertionError(f"reference sequence invalid: {refs[:3]}...{refs[-3:]}")
    print(f"wrote {MAIN_OUT.name} ({len(main_text)} chars)")
    print(f"wrote {PLAN_OUT.name} ({len(plan_text)} chars)")
    print(f"wrote {REPORT_OUT.name} ({len(report_text)} chars)")
    print("references: 1..50")


if __name__ == "__main__":
    main()
