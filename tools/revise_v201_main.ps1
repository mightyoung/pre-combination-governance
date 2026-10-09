param([Parameter(Mandatory=$true)][string]$Workspace)

$ErrorActionPreference = 'Stop'
$path = Join-Path $Workspace '00-论文-中文阅读稿v20.1-一致性修复与投稿主线收敛版.md'
$text = [System.IO.File]::ReadAllText($path, [System.Text.Encoding]::UTF8)

function Replace-Exact {
    param([string]$Source, [string]$Old, [string]$New, [string]$Label)
    $count = ([regex]::Matches($Source, [regex]::Escape($Old))).Count
    if ($count -ne 1) { throw "Replacement '$Label' expected once, found $count" }
    return $Source.Replace($Old, $New)
}

$text = Replace-Exact $text @'
# 面向动态过程安全的溯源约束证据融合：安全工件编译与组合前治理

*Provenance-Constrained Pre-Combination Governance for Dependent Evidence in Dynamic Process Safety*
'@ @'
# 面向动态过程安全的谱系依赖证据融合组合前治理：溯源约束与根级贡献守恒

*Provenance-Constrained Pre-Combination Governance for Lineage-Dependent Evidence in Dynamic Process Safety*
'@ 'title'

$text = Replace-Exact $text @'
动态过程安全评估需要联合工艺偏离、屏障状态、报警、检维修和派生分析，但同一物理根可经多个视图、模型与版本重复出现，物理共同原因也不等于观测谱系依赖。现有依赖组合方法通常估计依赖参数或改变组合规则；安全保证与工件追踪方法能够连接异构工件，却不直接约束同一证据在在线信念状态中的重复贡献。本文提出一种面向依赖不可验证场景的组合前治理架构。设计期安全工件首先编译为带允许映射、禁止推理和全追踪处置的 SafetyArtifactIR；PhysicalCouplingRegistry 与 ObservationLineageRegistry 分别管理物理耦合和信息生成谱系，任一关系不能证明时均失败关闭。同一 canonical root 的多场景主张只编译为一次 root-global joint valuation，RootRegistry、ActiveContributionLedger、速率门、重放、锁存与承诺状态在单一事务中维护。理论仅给出接受分支的支撑性锐界和固定执行轨迹敏感性，不解释为事故概率或现场安全保证。本文同时给出一套尚未执行的确认性研究蓝图，以可用性和行动 no-harm 门防止“永远拒绝”制造表面安全。当前版本不主张经验优越性；核心贡献是把安全工件的可用语义转化为可审计、可失败关闭的证据准入与生命周期贡献守恒合同。
'@ @'
动态过程安全评估需要联合工艺偏离、屏障状态、报警、检维修和派生分析，但同一物理采集可经视图、模型、版本与异步传播重复进入融合。已有工作已经研究依赖证据、信息谱系和重复祖先消除，因此本文不把“溯源”或“只计一次”本身作为新颖性。本文研究一个更窄的问题：当物理共同原因、观测生成谱系和映射有效性不能由内容相似度判定时，怎样在组合前阻断未裁决依赖，并在版本替换、合并、退休与重放中维持根级贡献一致。安全工件被编译为带允许映射、禁止推理和全追踪处置的 SafetyArtifactIR；PhysicalCouplingRegistry 与 ObservationLineageRegistry 分别管理物理耦合和信息生成谱系；root-level mapping、集合级资格和原子账本共同构成注册表相对的准入算子。正文给出归一合取更新算子、三个实现不变量及接受分支的支撑性敏感性界。尚未执行的确认性方案以共同主终点、可用性和行动 no-harm 门防止“永远拒绝”制造表面安全。当前版本不主张经验优越性，也不保证未登记共同原因、错误映射或错误安全工件；贡献限定为过程安全约束下、可失败关闭的组合前准入与生命周期治理合同。
'@ 'zh-abstract'

$text = Replace-Exact $text @'
Dynamic process-safety assessment combines process deviations, barrier states, alarms, maintenance records, and derived analytics. The same physical root may, however, reappear through multiple views, models, and versions, while physical common cause is not equivalent to observational lineage dependence. Existing dependent-evidence methods usually estimate dependence or modify a combination rule; assurance-case and artifact-tracing methods connect heterogeneous engineering artifacts but do not directly conserve a root's contribution to an online belief state. We propose a pre-combination governance architecture for settings in which dependence cannot be verified. Safety artifacts are compiled into a typed SafetyArtifactIR with permitted mappings, forbidden inferences, and total trace disposition. PhysicalCouplingRegistry and ObservationLineageRegistry separately govern physical coupling and information-generation lineage, and unresolved eligibility fails closed. Claims sharing one canonical root are compiled once into a root-global joint valuation, while registry, ledger, rate, replay, latch, and commitment state are maintained atomically. The theoretical results are limited to a supporting accepted-branch bound and fixed-trace sensitivity; they are not accident probabilities or plant-safety guarantees. An unexecuted confirmatory blueprint couples co-primary decision endpoints with availability and action no-harm gates so that blanket abstention cannot manufacture apparent safety. No empirical superiority is claimed in this version. The contribution is an auditable lifecycle contract for evidence admission and contribution conservation.
'@ @'
Dynamic process-safety assessment combines process deviations, barrier states, alarms, maintenance records, and derived analytics, yet one physical acquisition may re-enter fusion through views, models, versions, and asynchronous propagation. Prior work already addresses dependent evidence, information lineage, and duplicate removal; provenance or once-only accounting alone is therefore not our novelty. We study a narrower problem: how to block unresolved dependence before combination when physical common cause, observational lineage, and mapping validity cannot be inferred from content similarity, while preserving root-level contribution consistency under supersession, merge, retirement, and replay. Safety artifacts are compiled into a typed SafetyArtifactIR with permitted mappings, forbidden inferences, and total trace disposition. Separate physical-coupling and observation-lineage registries, a preregistered root-level mapper, setwise eligibility, and an atomic ledger form a registry-relative admission operator. We state the normalized conjunctive update explicitly, distinguish three implementation invariants from a supporting accepted-branch sensitivity bound, and provide an unexecuted confirmatory design with co-primary endpoints, availability, and action no-harm gates. No empirical superiority is claimed. Guarantees do not cover unregistered common causes, incorrect mappings, or incorrect safety artifacts.
'@ 'en-abstract'

$text = Replace-Exact $text @'
仍未被充分解决的是**依赖不可验证时的在线贡献治理**。同一采集 epoch 可被 DCS 告警、软测量、人工记录、规则和 AI 摘要多次表达；不同 root 也可能共享模型、总线、校准、维护活动或公用工程。消息数量因而不等于独立信息量。依赖组合、未知相关融合、来源行为解释和 provenance 表示分别处理其中一部分 [13], [17–22], [25], [27], [28], [30–33], [37–44]，但通常没有共同回答：同一物理根能否在多视图、多场景、多主体和多版本下再次累计；关系不能证明时如何失败关闭；既有贡献在 merge、supersede、retire 和 replay 中如何不被复制或退款。
'@ @'
仍未被充分解决的是**过程安全语义约束下、谱系依赖不可验证时的在线准入与生命周期一致性**。同一采集 epoch 可被 DCS 告警、软测量、人工记录、规则和 AI 摘要多次表达；不同 root 也可能共享模型、总线、校准、维护活动或公用工程。消息数量因而不等于独立信息量。依赖组合、未知相关融合、来源行为解释、provenance 表示与谱系去重已经分别处理其中的重要部分 [13], [17–22], [25], [27], [28], [30–33], [36–44]。本文不提出未知依赖估计器，也不声称首次解决重复融合；它只回答在安全工件给出有限允许语义、且依赖仍有 UNKNOWN 状态时，怎样把准入、版本、merge、supersede、retire 与 replay 约束到同一失败关闭合同。
'@ 'gap-boundary'

$text = Replace-Exact $text @'
贡献限定为两项。第一，提出从 SafetyArtifactIR 到组合前关系资格、RootClaimBundle、RootRegistry/ActiveContributionLedger 和 replay-safe 状态机的统一架构；新增点不是又一种组合公式，而是把安全工件允许语义、物理耦合、观测谱系、版本血缘和 fail-closed 诊断编译为同一可执行合同。第二，给出接受分支的支撑性锐界、固定执行轨迹内容替换包络，以及把系统级主张、机制主张和降级措辞预先绑定的验证框架。后者是研究设计，不是当前版本的经验贡献。
'@ @'
贡献限定为两项。第一，提出一个注册表相对的组合前准入算子：给定经认证的 root-equivalence closure、预注册且经联合校准的 root-level observation mapping，以及声明完备的观测生成图，该算子阻断已登记重复和未裁决依赖的新增贡献，并在 merge、supersede、retire 与 replay 中维持已提交根贡献的一致性。SafetyArtifactIR 是该算子在过程安全域的约束编译前端，而不是通用安全本体。第二，给出接受分支的支撑性锐界、固定执行轨迹内容替换包络，以及把系统级主张、机制主张和降级措辞预先绑定的验证框架。上述保证不覆盖未登记共同原因、错误 mapping、错误安全工件或持有合法凭证的恶意主体；验证框架也不是当前版本的经验贡献。
'@ 'contributions'

$text = Replace-Exact $text @'
ACCESS 可把演化的 model-based assurance case 连接到异构工程工件并在开发期和运行期评价 [5]；Andromeda 通过元模型连接安全案例、系统模型、安全活动、标准和论证模式 [6]；工业研究进一步表明安全/安保相关工件的分类与追踪高度依赖上下文、组织和工具 [36]。因此，“连接安全工件”“建立 trace”或“支持运行期保证”本身不是本文的新颖性。
'@ @'
ACCESS 可把演化的 model-based assurance case 连接到异构工程工件并在开发期和运行期评价 [5]；Andromeda 通过元模型连接安全案例、系统模型、安全活动、标准和论证模式 [6]。面向分布式融合的 PRIMEX-PEV 已使用唯一观测/来源身份编码谱系、消除冗余祖先并合并互补谱系 [36]。因此，“连接安全工件”“建立 trace”“谱系传播”或“去除重复祖先”本身都不是本文的新颖性。
'@ 'prior-art'

$text = Replace-Exact $text @'
| ACCESS / Andromeda / 工件追踪 [5], [6], [36] | 保证案例与工程工件的连接、维护和追踪 | 工件语义对信念准入与贡献守恒的约束 | 编译正负测试 |
'@ @'
| ACCESS / Andromeda [5], [6] | 保证案例与工程工件的连接、维护和追踪 | 工件语义对信念准入的有限允许/禁止约束 | 编译正负测试 |
| belief-function provenance / PRIMEX-PEV [13], [36] | 组合过程谱系、冗余祖先消除和动态谱系传播 | 物理根与观测谱系分层、UNKNOWN 失败关闭及安全动作边界 | 谱系重复/遗漏/版本重放压力测试 |
'@ 'nearest-neighbor-row'

$text = Replace-Exact $text @'
本文最可辨识的定位因此是：**面向依赖不可验证场景的、可审计的组合前证据准入与生命周期贡献守恒架构**。理论与过程安全应用均服务于这一主线。
'@ @'
本文最可辨识的定位因此是：**过程安全工件约束下、区分物理观测事件与观测谱系并保留 UNKNOWN 状态的组合前准入，以及跨版本/合并/退休/重放的原子贡献一致性**。这一定位比“provenance-aware once-only fusion”更窄；后者已有直接近邻 [13], [36]。本文中的 root 是带有效时间区间和因果边界的观测/采集事件，不是设备或人员实体；同一设备在不同采集 epoch 产生的新观测可形成新 root。
'@ 'positioning'

$text = Replace-Exact $text @'
在预签 within-root coupling 假设下，确认性实现不把 \(J_o\) 留作 oracle，而固定为**共享潜变量的 consonant random-set compiler**；共享 \(u\) 是保守依赖模型，不是 provenance 自动推出的事实。每条胜出 typed claim 的签名 mapping manifest 给出同一 \(u\in(0,1]\) 上右连续、有限断点、嵌套焦元日程 \(A_r(u)\)；断点由 calibration/reliability/lateness 工件以有理数冻结。编译器取所有断点的共同分割，在每个区间只计算一次
'@ @'
确认性主分析不再把“多个独立校准 view 共用同一个 \(u\)”当作天然保守。首选合同是由独立 pilot 联合校准的 root-level mapper

$$f_o(\{x_r,q_r\}_r,c)\longrightarrow \mathcal V_o,$$

其输入、允许 view 集、校准目标、覆盖误差和适用域在解封前冻结。若只能获得 per-view consonant schedule，则必须预注册一组允许的 within-root couplings \(\mathcal K_o\)，对所有 \(\kappa\in\mathcal K_o\) 计算决策/风险包络；若 SAFE 或方法排序随 coupling 改变，强制 `COUPLING_SENSITIVE`，不得进入确认性 SAFE 结论。共享 \(u\) 交集编译器仅保留为一个具名敏感性模型，不再声称一般保守。对该模型，每条胜出 typed claim 的 manifest 给出同一 \(u\in(0,1]\) 上右连续、有限断点、嵌套焦元日程 \(A_r(u)\)，编译器取共同分割并在每个区间只计算一次
'@ 'root-mapper'

$oldRegistry = 'RootRegistry 对每个由签名 RootIdentityManifest 唯一认证的 canonical root 建立条目，并把根级 lifecycle_status 与版本级 append-only attempt_status 分开。前者只取 UNCOMMITTED、ACTIVE、NONCONTRIBUTING、RETIRED、MERGED；后者包含 QUARANTINED、ABSTAIN_COMPLEXITY、ABSTAIN_RATE、ABSTAIN_RELATION、ABSTAIN_CONFLICT、ABSTAIN_BUDGET、SUPERSEDE_PRINCIPAL_BLOCKED、TARGET_SCOPE_CHANGE_BLOCKED 或 ACCEPTED。'
$newRegistry = 'RootRegistry 对每个由签名 RootIdentityManifest 唯一认证的 canonical root 建立条目，并把根级 lifecycle_status 与按 `(bundle_version,event_id)` 追加的 attempt log 分开。前者只取 UNCOMMITTED、ACTIVE、NONCONTRIBUTING、RETIRED、MERGED；后者的 `attempt_status` 包含 QUARANTINED、ABSTAIN_MAPPING、ABSTAIN_COMPLEXITY、ABSTAIN_RATE、ABSTAIN_RELATION、ABSTAIN_CONFLICT、ABSTAIN_BUDGET、SUPERSEDE_PRINCIPAL_BLOCKED、TARGET_SCOPE_CHANGE_BLOCKED 或 ACCEPTED。同一版本可有多个 transport/裁决事件，禁止用 `attempt_status[version]` 覆盖既往记录。'
$text = Replace-Exact $text $oldRegistry $newRegistry 'registry-enum'

$text = Replace-Exact $text @'
因此，pairwise ELIGIBLE 不能推出集合级 ELIGIBLE。这里的 ELIGIBLE 只表示“在注册表完备性和声明条件独立假设下获准组合”，不表示用有限数据证明了真实独立。物理状态依赖、条件观测依赖和身份/派生重复分三层处理：已建模物理依赖进入 factor graph；未建模且可能诱发观测相关的共享原因阻断组合；身份或派生重复始终由 root/class 规则去重。
'@ @'
因此，pairwise ELIGIBLE 不能推出集合级 ELIGIBLE。证书必须由冻结算法生成，而不是人工签名断言：构造 candidate 与 ACTIVE roots 的 derivation、observation-generation 和 physical-latent 图并取祖先闭包；先收缩已由 joint factor 显式建模且有校准证据的潜变量；若存在 identity/derivation 重叠、未建模共同祖先、未裁决高阶超边、过期边、context 不匹配或 registry completeness 缺口，则返回 BLOCKED/UNKNOWN 及最小见证子图；仅当全部相关路径均被裁决且随机集生成语义满足预注册 distinctness 充分条件时才返回 ELIGIBLE。复杂度为冻结图表示上的 \(O(|V|+|E|+|H|)\)，超 cap 为 ABSTAIN_COMPLEXITY。这里的 ELIGIBLE 只表示“相对于注册表、映射模型和声明完备性获准组合”，不表示用有限数据证明了真实独立。
'@ 'setwise-algorithm'

$oldRoute = '入口前置顺序唯一为：最小身份认证；identity-valid 后注册 TTL；递归解析 redirect；若已 RETIRED 则在 duplicate、outer、compiler 与 latch 前唯一 RETIRED_LATE_AUDIT；否则执行 outer validation；outer failure 走路由 1；仅 outer-valid envelope 才比较 exact duplicate 并可走路由 2；其余才判 class_record 并运行适用的 \(J_o/J_{merge}\)。因此同一已被 outer 拒绝的字节重传仍只能再次 QUARANTINED，绝不能借 duplicate 短路。signature failure 只在 outer 层，普通候选的 compiler semantic/cap failure 才进入后续路由；confirmed-equivalence committed MERGE 适用前述 fail-stop 例外。'
$newRoute = '入口前置顺序唯一为：最小身份认证并冻结 TTL；以 event_id 幂等键提交一次 processing token；递归解析 redirect；若已 RETIRED 则唯一 RETIRED_LATE_AUDIT；否则执行 outer validation；仅 outer-valid envelope 才比较 exact duplicate；非重复候选执行 SourceAdapter mapping；映射成功后才运行适用的 \(J_o/J_{merge}\) 与 ScopeClosure；随后重建 SetwiseEligibilityCertificate；仅集合 ELIGIBLE 才进入预算、速率和 joint gate。retired、outer-invalid、mapping/compiler 失败事件均收费一次，CAS retry 不重复收费。任何 S1/S2 顺序差异均使 package validation 失败。'
$text = Replace-Exact $text $oldRoute $newRoute 'route-order'

$text = Replace-Exact $text @'
7. 在任何动作输出前更新 replay/latch/ISCM 状态；不可用、锁存、UTILITY_SENSITIVE 或 mandatory replay 未闭合时禁止 SAFE_ELIGIBLE。
'@ @'
7. 在任何动作输出前更新 replay/latch/ISCM 状态；不可用、锁存、UTILITY_SENSITIVE、COUPLING_SENSITIVE 或 mandatory replay 未闭合时禁止 SAFE_ELIGIBLE。

对通过第 5 步的候选，正文中的融合更新唯一为

$$
q_o=D_{\beta^{eff}}(\mathcal V_o),\qquad
\widetilde b_k=\mathbb B_{k^-}\odot q_o,\qquad
s_k=1-\widetilde b_k(\varnothing),
$$

其中 \(D_{\beta}\) 为 Shafer 折扣，\(\odot\) 为未归一合取。仅当 \(s_k\ge\delta_k\) 时提交

$$
\mathbb B_k(A)=\mathcal N(\widetilde b_k)(A)=
\frac{\widetilde b_k(A)}{s_k},\quad A\ne\varnothing,
\qquad \mathbb B_k(\varnothing)=0.
$$

否则提交预测态 \(\mathbb B_{k^-}\) 与具名失败状态；任何分支都禁止按场景边缘分别归一后再融合。
'@ 'explicit-operator'

$text = Replace-Exact $text @'
&R^+<\tau_{\mathrm{safe}},\quad W\le\eta_{\mathrm{safe}},\quad
'@ @'
&\sup_{u\in\mathcal U_h}R_u^+<\tau_{\mathrm{safe}},\quad
\sup_{u\in\mathcal U_h}W_u\le\eta_{\mathrm{safe}},\quad
'@ 'utility-equation'

$text = Replace-Exact $text @'
式 (3) 中 \(R^+,W\) 按 §3.2 冻结的效用族最不利成员评估（robust SAFE）；升级类阈值使用签署默认 \(u_h^0\) 并承担敏感性披露义务（P-1）。
'@ @'
式 (3) 对冻结效用族逐项取最不利值；若任一允许效用改变 SAFE/非 SAFE 或行动排序，则设置 UTILITY_SENSITIVE 并阻断 SAFE，不能改用默认效用继续。
'@ 'utility-policy'

$text = Replace-Exact $text '## 5 条件理论保证' '## 5 条件实现性质与支撑性理论' 'section5-title'
$text = Replace-Exact $text '**命题 1（Root/View Invariance）。**' '**实现不变量 1（Root/View Invariance）。**' 'invariant1'
$text = Replace-Exact $text '**命题 2（Replay/Canonicalization Equivalence）。**' '**实现不变量 2（Replay/Canonicalization Equivalence）。**' 'invariant2'
$text = Replace-Exact $text '**命题 3（Setwise Eligibility Soundness，条件式）。**' '**实现不变量 3（Setwise Eligibility Relative Soundness，条件式）。**' 'invariant3'
$text = Replace-Exact $text @'
三项性质的机械 oracle、反例和证明细节见 S1-v20；运行字段与失败码见 S2-v20。它们是本文主线性质，以下 \(1/\delta\) 结果只作为接受分支的数值稳定性支撑。
'@ @'
三项不变量由规范构造与性质测试保证，不作为新的数学定理；机械 oracle、反例和归纳证明义务见 S1-v20.1，运行字段与失败码见 S2-v20.1。以下 \(1/\delta\) 结果才是接受分支的数学支撑。
'@ 'invariant-boundary'

$text = Replace-Exact $text @'
当前可成立的贡献是架构、合同和条件理论，而不是经验优越性。v6.5 将系统级改善、组件 no-harm、hazard–barrier 增量和预算机制增量分别绑定到可否证 estimand。后续论文强度必须由参考实现、性质测试、独立物理资格、预注册确认实验和至少一项外部支持决定；未获证据支持的机制应从题名和核心贡献删除。
'@ @'
当前可成立的贡献是架构、合同、实现不变量和接受分支理论，而不是经验优越性。v6.7 将系统级改善、组件 no-harm、hazard–barrier 增量和预算机制增量分别绑定到可否证 estimand。后续论文强度必须由参考实现、性质测试、独立物理资格、预注册确认实验和至少一项外部支持决定；未获证据支持的机制应从题名和核心贡献删除。
'@ 'conclusion-version'

$text = Replace-Exact $text @'
当前仓库包含 19 个 Python 文件、共 1,397 个物理行（其中 1,192 行 Python 非空）、面向早期 v5 架构的 `risk-fusion-bench` 原型；它不实现 v20/v6.5 的 SafetyArtifactIR、RootClaimBundle、双注册表、生命周期账本和确认性分析合同，因而不作为本文结果来源。准确表述是：**v20/v6.5 合同一致的参考实现尚未完成**，而不是“仓库中没有代码”。投稿前应公开 schema/compiler、状态机、性质测试、生成器、容器、分析代码、密封 manifest、缓存输出和匿名复现链接。
'@ @'
仓库包含一个不符合 v20.1/v6.7 合同的 legacy-v5 原型；本文不从该原型提取结果。合同一致的参考实现尚未完成。投稿前应公开 schema/compiler、状态机、性质测试、生成器、容器、分析代码、密封 manifest、缓存输出和匿名复现链接。
'@ 'code-statement'

$text = Replace-Exact $text @'
[36] M. Herrmann, A. Specht, A. Sekerci, M. Obaidi, M. Ehl, D.A.A. Elsofi, K. Großer, J. Klünder, J. Jürjens, K. Schneider, From missile warhead to smart fridge: Interviews with industry experts on tracing safety- and security-relevant artifacts, J. Syst. Softw. 230 (2025) 112551. https://doi.org/10.1016/j.jss.2025.112551.
'@ @'
[36] K.-C. Chang, S.-M. Kuo, Y. Bar-Shalom, C.-Y. Chong, S. Mori, Encoding information lineage for scalable distributed fusion, J. Adv. Inf. Fusion 20(2) (2025) 152–171. https://isif.org/media/encoding-information-lineage-scalable-distributed-fusion.
'@ 'reference36'

$text = $text.Replace('v20/v6.5', 'v20.1/v6.7').Replace('v20/v6.5', 'v20.1/v6.7')
$utf8 = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllText($path, $text, $utf8)
Write-Output "Revised $path"
