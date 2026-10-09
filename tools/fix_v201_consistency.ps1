$ErrorActionPreference = 'Stop'

function Read-Utf8([string]$Path) {
    return [System.IO.File]::ReadAllText((Resolve-Path -LiteralPath $Path), [System.Text.Encoding]::UTF8).Replace("`r`n", "`n")
}

function Write-Utf8([string]$Path, [string]$Text) {
    $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText((Resolve-Path -LiteralPath $Path), $Text, $utf8NoBom)
}

function Replace-One([string]$Text, [string]$Old, [string]$New, [string]$Label) {
    $Old = $Old.Replace("`r`n", "`n")
    $New = $New.Replace("`r`n", "`n")
    $count = ([regex]::Matches($Text, [regex]::Escape($Old))).Count
    if ($count -ne 1) {
        throw "[$Label] expected one literal match, found $count"
    }
    return $Text.Replace($Old, $New)
}

function Replace-RegexOne([string]$Text, [string]$Pattern, [string]$Replacement, [string]$Label) {
    $count = ([regex]::Matches($Text, $Pattern)).Count
    if ($count -ne 1) {
        throw "[$Label] expected one regex match, found $count"
    }
    return [regex]::Replace($Text, $Pattern, $Replacement, 1)
}

$mainPath = '00-论文-中文阅读稿v20.1-一致性修复与投稿主线收敛版.md'
$s1Path = '补充材料S1-v20.1-组合前治理证明与性质测试.md'
$s2Path = '补充材料S2-v20.1-运行合同与观察映射规范.md'
$expPath = '实验设计与执行计划v6.7-精简确认性预注册蓝图.md'

# -----------------------------------------------------------------------------
# Main manuscript
# -----------------------------------------------------------------------------
$t = Read-Utf8 $mainPath

$old = @'
| C-Audit：安全工件只产生被授权的运行语义 | 编译器正/负性质测试、total trace disposition、非法映射 fail-closed | 任一越权映射即撤回“安全工件编译正确性” |
| C-Conserve：同一 root 不因视图、版本或 replay 重复贡献 | duplicate/Sybil/version/replay/merge 属性测试与账本守恒 | 任一重复贡献即否证核心架构 |
| C-System：A 在共同服务合同下改善危险决策 | A 对冻结唯一 G* 的共同主终点、组件 no-harm 与资格门 | 未通过仅报告性质测试，不写性能优越 |
| C-HB：显式 hazard–barrier 语义有增量 | 与保持同一 demand clock 的匹配消融比较 | 未通过则过程安全只保留为应用域 |
| C-Budget：多轴预算有独立机制价值 | M4−M3 的预签 estimand、SESOI、no-harm 和功效 | 未通过不得进入题名或核心贡献 |
'@
$new = @'
| C-Audit：安全工件只产生被授权的运行语义 | 编译器正/负性质测试、total trace disposition、非法映射 fail-closed | 任一越权映射即撤回“安全工件编译正确性” |
| C-Conserve-Inv：同一 root 不因视图、版本或 replay 重复贡献 | duplicate/Sybil/version/replay/merge 属性测试与账本守恒 | 任一重复贡献即否证核心架构并阻断全部性能检验 |
| C-System：A 在共同服务合同下达到危险决策与行动时延的预签改善幅度 | A 对冻结唯一 G* 的共同主终点、组件 no-harm 与资格门 | 未越过两个 SESOI 或任一 no-harm 失败，仅作描述性报告 |
| C-HB：显式 hazard–barrier 语义有增量 | 与保持同一 demand clock 的匹配消融比较 | 未通过则过程安全只保留为应用域 |
| C-Conserve-Benefit：生命周期治理相对 lineage-only/无账本变体具有经验增量 | A 对 A^-Ledger/A^-Scope 的对抗轨迹、决策和可用性 estimand | 未通过不否定已通过的 C-Conserve-Inv，但不得声称治理带来性能收益 |
| C-Budget：多轴预算有独立机制价值 | M4−M3 的预签 estimand、SESOI、no-harm 和功效 | 未通过不得进入题名或核心贡献 |
'@
$t = Replace-One $t $old $new 'main claim table'

$t = Replace-One $t '本文中的 root 是带有效时间区间和因果边界的观测/采集事件，不是设备或人员实体；同一设备在不同采集 epoch 产生的新观测可形成新 root。' '本文中的 root 是带有效时间区间和因果边界的观测/采集事件，不是设备或人员实体；同一设备在不同采集 epoch 产生的新观测可形成新 root。该边界不是自由文本：签名 AcquisitionManifest 必须绑定 Eventifier id/version/hash、可信 clock domain、区间 $[t_{start},t_{end})$、causal_boundary_id/hash、原始采集身份与分段证据，RootIdentityManifest 再绑定该 manifest 的 hash。' 'main root definition'

$t = Replace-One $t '冻结 Eventifier 按工况阶段、变化点规则和最大持续时间把连续流切成物理采集 epoch。只有新的物理采集、独立 proof-test 或独立观察才形成新 root_epoch_id；滑窗、重采样、转述、重读旧记录和重新运行模型均继承原根。' '冻结 Eventifier 按工况阶段、变化点规则和最大持续时间把连续流切成物理采集 epoch。只有新的物理采集、独立 proof-test 或独立观察才形成新 root_epoch_id；滑窗、重采样、转述、重读旧记录和重新运行模型均继承原根。Eventifier 规则、区间与 causal boundary 必须进入签名 AcquisitionManifest 并由 RootIdentityManifest 的 acquisition_manifest_hash 间接认证；TTL 只表示 registry 服务寿命，不能代替观测有效区间。' 'main Eventifier binding'

$old = @'
SafetyArtifactIR 不估计 BPA，也不证明运行观测真实。每个来源必须通过版本化 adapter

$$
f_{s,\theta}:(x_{s,t},q_{s,t},c_t)\mapsto
(A_s(u),\mathrm{CalibrationCertificate}_s,\mathrm{ValidityDomain}_s)
$$

把原始观测 \(x_{s,t}\)、质量标记 \(q_{s,t}\) 和运行上下文 \(c_t\) 映射为 typed focal-set schedule。证书必须绑定训练/校准数据、校准误差与覆盖目标、缺失处理、迟到策略、适用工况、漂移/OOD 检测、adapter/schema/code hash 和失效动作。certificate 缺失/过期、适用域超界、漂移/OOD 与其他未知映射分别返回 MAPPING_CERTIFICATE_INVALID、MAPPING_VALIDITY_DOMAIN_EXCEEDED、MAPPING_DRIFT_DETECTED 或 MAPPING_UNKNOWN；四者均强制 ABSTAIN_MAPPING，不能生成可合取 claim。

同一 root 内的共享潜变量 \(u\) 是预注册的 within-root coupling 假设，而不是 provenance 自动推导的事实。确认性结果必须报告该 coupling 下的 mapping acceptance/abstention，并对预签替代 coupling 做敏感性分析；若数据不能支持一般性，结论限定为 bounded exact factorization 下的 consonant root claims。
'@
$new = @'
SafetyArtifactIR 不估计 BPA，也不证明运行观测真实。每个来源必须先通过版本化 SourceAdapter

$$
f_{s,\theta}:(x_{s,t},q_{s,t},c_t)\mapsto
z_{s,t}=(\mathrm{TypedFeature}_s,A_s^{optional}(u),\mathrm{CalibrationCertificate}_s,\mathrm{ValidityStatus}_s),
$$

把原始观测 \(x_{s,t}\)、质量标记 \(q_{s,t}\) 和运行上下文 \(c_t\) 映射为已认证的 root-mapper input；可选的 per-view focal schedule 只供预签 coupling 敏感性臂使用。证书必须绑定训练/校准数据、校准误差与覆盖目标、缺失处理、迟到策略、适用工况、漂移/OOD 检测、adapter/schema/code hash 和失效动作。certificate 缺失/过期、适用域超界、漂移/OOD 与其他未知映射分别返回 MAPPING_CERTIFICATE_INVALID、MAPPING_VALIDITY_DOMAIN_EXCEEDED、MAPPING_DRIFT_DETECTED 或 MAPPING_UNKNOWN；四者均强制 ABSTAIN_MAPPING，不能生成可合取 claim。

主路径的 RootLevelMapperManifest 冻结允许的 adapter/output schema 集、输入排序、联合校准数据与目标、覆盖误差、适用域、代码/容器 hash 和 failure policy；\(J_o/J_{merge}\) 只消费同一 sealed bundle 中的 \(z_{s,t}\)，不得绕过 SourceAdapter 重新读取未认证 raw input。仅在主 mapper 不可用且协议预签时，per-view schedules 才送入冻结的 coupling family \(\mathcal K_o\) 计算包络。共享潜变量 \(u\) 只是 \(\mathcal K_o\) 中一个具名共单调模型；SAFE 或方法排序随 coupling 改变时唯一返回 COUPLING_SENSITIVE，不得形成确认性 SAFE。
'@
$t = Replace-One $t $old $new 'main mapping interface'

$t = Replace-One $t '对应性质测试见 S1-v20。' '对应性质测试见 S1-v20.1。' 'main stale S1 ref'

$t = Replace-One $t 'TraceEdge 是多对多关系，不要求双射。每个编译输出至少有一个合法来源；每个规范性输入条目必须标记 `COMPILED`、`INTENTIONALLY_UNMAPPED(reason)` 或 `REJECTED(code)`；无源输出、未处置输入、非法单位、缺失 schema/rule hash、从禁止列越权推理或 context 未绑定均失败关闭。编译结果包括 schema/version、单位、源工件哈希、规则哈希、输出哈希、全部诊断和 typed failure code。NormativeReleaseManifest 同时绑定主文、S1、S2、实验协议、IR schema 和 compiler；任何冲突或 hash 不一致使整个 release 无效，不存在“以更保守者为准”或补充材料优先。' 'TraceEdge 是多对多关系，不要求双射。每个编译输出至少有一个合法来源；每个规范性输入条目必须标记 `COMPILED`、`INTENTIONALLY_UNMAPPED(reason)` 或 `REJECTED(code)`；无源输出、未处置输入、非法单位、缺失 schema/rule hash、从禁止列越权推理或 context 未绑定均失败关闭。编译结果包括 schema/version、单位、源工件哈希、规则哈希、输出哈希、全部诊断和 typed failure code。NormativeReleaseManifest 的唯一最低字段合同定义于 S2.0，并至少绑定主文、S1、S2、v6.7、ClaimRegister、IR/schema/compiler、RootIdentity/AcquisitionManifest schema、Eventifier、SourceAdapter/RootLevelMapper/coupling-family registries、SetwiseEligibilityGenerator、OperationalSafetyArtifact、Method/ArmFrame、Seed/Allocation/Test manifests、分析容器及依赖 DAG；任何必需 hash 为 PENDING、冲突或不匹配均使确认性 release 无效，不存在“以更保守者为准”或补充材料优先。' 'main manifest contract'

$t = Replace-One $t '确认性主分析不再把“多个独立校准 view 共用同一个 \(u\)”当作天然保守。首选合同是由独立 pilot 联合校准的 root-level mapper' '确认性主分析不再把“多个独立校准 view 共用同一个 \(u\)”当作天然保守。首选合同是在不参与功效核或 G* 选择的独立 `D_mapper_cal` 上联合校准、并在 `D_mapper_qual` 上冻结资格的 root-level mapper' 'main mapper calibration split'
$t = Replace-One $t '$$f_o(\{x_r,q_r\}_r,c)\longrightarrow \mathcal V_o,$$' '$$f_o(\{z_r\}_r,c)\longrightarrow \mathcal V_o,$$' 'main mapper formula'

$t = Replace-One $t '后者的 `attempt_status` 包含 QUARANTINED、ABSTAIN_MAPPING、ABSTAIN_COMPLEXITY、ABSTAIN_RATE、ABSTAIN_RELATION、ABSTAIN_CONFLICT、ABSTAIN_BUDGET、SUPERSEDE_PRINCIPAL_BLOCKED、TARGET_SCOPE_CHANGE_BLOCKED 或 ACCEPTED。' '后者的 `attempt_status` 包含 QUARANTINED、ABSTAIN_MAPPING、ABSTAIN_COMPLEXITY、ABSTAIN_RATE、ABSTAIN_RELATION、ABSTAIN_SENSITIVITY、ABSTAIN_CONFLICT、ABSTAIN_BUDGET、SUPERSEDE_PRINCIPAL_BLOCKED、TARGET_SCOPE_CHANGE_BLOCKED 或 ACCEPTED。' 'main attempt enum'

$t = Replace-One $t '仅当全部相关路径均被裁决且随机集生成语义满足预注册 distinctness 充分条件时才返回 ELIGIBLE。复杂度为冻结图表示上的 \(O(|V|+|E|+|H|)\)，超 cap 为 ABSTAIN_COMPLEXITY。' '仅当全部相关路径均被裁决且随机集生成语义满足预注册 distinctness 充分条件时才返回 ELIGIBLE。证书同时绑定 generator version/hash、算法语义版本、cap/policy hash、adjudication-policy hash 与最小见证子图/hash。复杂度为冻结图表示上的 \(O(|V|+|E|+|H|)\)，超 cap 为 ABSTAIN_COMPLEXITY。' 'main setwise generator fields'

$t = Replace-One $t '入口前置顺序唯一为：最小身份认证并冻结 TTL；以 event_id 幂等键提交一次 processing token；递归解析 redirect；若已 RETIRED 则唯一 RETIRED_LATE_AUDIT；否则执行 outer validation；仅 outer-valid envelope 才比较 exact duplicate；非重复候选执行 SourceAdapter mapping；映射成功后才运行适用的 \(J_o/J_{merge}\) 与 ScopeClosure；随后重建 SetwiseEligibilityCertificate；仅集合 ELIGIBLE 才进入预算、速率和 joint gate。retired、outer-invalid、mapping/compiler 失败事件均收费一次，CAS retry 不重复收费。' '入口前置顺序唯一为：最小身份认证；认证失败唯一写 QuarantineLog(reason=CREDENTIAL_CHAIN_INVALID 或 ROOT_IDENTITY_MANIFEST_SIGNATURE_INVALID, action=REJECT_AUTH)，不建立 RootRegistry、不写 attempt、不冻结 TTL且不收费；认证成功才冻结 TTL，并以 event_id 幂等键提交一次 processing token；递归解析 redirect；若已 RETIRED 则唯一 RETIRED_LATE_AUDIT；否则执行 outer validation；仅 outer-valid envelope 才比较 exact duplicate；非重复候选执行 SourceAdapter mapping；映射成功后才运行适用的 \(J_o/J_{merge}\) 与 ScopeClosure；随后重建 SetwiseEligibilityCertificate；仅集合 ELIGIBLE 才进入预算、速率和 joint gate。identity-valid 的 retired、outer-invalid、mapping/compiler 失败事件均收费一次，CAS retry 不重复收费。' 'main entry order auth'

$routePattern = '(?ms)^1\. \*\*REJECT_SCHEMA\*\*：.*?^8\. \*\*CONJUNCTIVE\*\*：.*?$'
$routeReplacement = @'
1. **REJECT_AUTH**：credential chain 或 RootIdentityManifest signature 无法验证时，仅写 QuarantineLog；reason_code 分别为 CREDENTIAL_CHAIN_INVALID 或 ROOT_IDENTITY_MANIFEST_SIGNATURE_INVALID，action=REJECT_AUTH，RootRegistry attempt_status=NO_ATTEMPT。不得建立/修改 Registry、冻结 TTL、运行 predictor 之外的候选逻辑或收取 processing token。
2. **REJECT_SCHEMA**：identity-valid 且未退休，但 root_type、schema_version、AcquisitionManifest/Eventifier/interval/causal-boundary 与 RootIdentityManifest 的唯一绑定、outer envelope 字段、签名/哈希、时间、seq、seal、expected-slot equality 或版本规则无效时，按冻结 outer reason_code 写 action=REJECT_SCHEMA、attempt_status=QUARANTINED；若条目新建则 lifecycle_status=UNCOMMITTED，既有生命周期绝不覆盖；processing 已收费一次。outer validator 不检查随机集嵌套、target-scope 语义或 intrabundle discord。
3. **DUPLICATE_AUDIT**：仅当当前 envelope 已 outer-valid，且 canonical root、bundle_version、envelope_hash 与既有 outer-valid adjudicated envelope 完全相同；只更新 last_seen/retry_count/audit，不写 attempt。每个不同 transport event_id 收一次 processing token；同 event_id CAS retry 幂等，不重复收费。
4. **ABSTAIN_MAPPING**：outer-valid candidate 在任何 \(J_o/J_{merge}\)、关系、预算或 gate 之前，若 SourceAdapter 返回 MAPPING_CERTIFICATE_INVALID、MAPPING_VALIDITY_DOMAIN_EXCEEDED、MAPPING_DRIFT_DETECTED 或 MAPPING_UNKNOWN，则 action=ABSTAIN_MAPPING、attempt_status=ABSTAIN_MAPPING；不得生成 typed root-mapper input 或集合证书。相对预测态不改变 belief、ActiveLedger、budget、rate 或 GateState；Registry 只追加 attempt，并将 never-committed 条目置 NONCONTRIBUTING，committed lifecycle/token 保持。
5. **ABSTAIN_COMPLEXITY**：新候选、ROOT_SUPERSEDE 或 CLASS_SUPERSEDE 的 compiler/结构 cap 超限时，reason_code=COMPILER_CAP_EXCEEDED、action=ABSTAIN_COMPLEXITY、attempt_status=ABSTAIN_COMPLEXITY；仅 never-committed 条目置 NONCONTRIBUTING，既有 committed lifecycle/token 保持，并 LATCH_SET。mandatory ROOT_RETIRE/MERGE replay 超限只进入 SAFE_HALT_REPLAY_CAP。
6. **ABSTAIN_RELATION（compiler）**：\(J_o/J_{merge}\) 返回 MAPPING_INVALID、TARGET_SCOPE_CONFLICT、STRUCTURAL_CONSTRAINT_FAIL、NO_EVIDENCE 或 INTRABUNDLE_DISCORD 时，reason_code 保留原值，action=ABSTAIN_RELATION、attempt_status=ABSTAIN_RELATION；仅 never-committed root/class 可置 NONCONTRIBUTING，committed lifecycle/token 保持。
7. **SEEN ROOT/CLASS**：未到期 non-class root 的高版本，ever_committed=false 走 INITIALIZE_REGISTERED_ROOT，true 走 ROOT_SUPERSEDE；class member 分别走 INITIALIZE_REGISTERED_CLASS/CLASS_SUPERSEDE。ordinary supersede 新主体不足时 reason_code=SUPERSEDE_PRINCIPAL_CAP、action=SUPERSEDE_PRINCIPAL_BLOCKED、attempt_status 同 action；target 集变化时 reason_code=TARGET_SCOPE_CHANGE、action=TARGET_SCOPE_CHANGE_BLOCKED、attempt_status 同 action。
8. **ABSTAIN_RELATION（setwise）**：SETWISE_CERTIFICATE_MISSING、SETWISE_HIGHER_ORDER_UNRESOLVED、SETWISE_REGISTRY_INCOMPLETE、SETWISE_CONTEXT_STALE 或 SETWISE_BLOCKED 均强制 action=ABSTAIN_RELATION、attempt_status=ABSTAIN_RELATION；相对预测态不作 fusion，不改变 ActiveLedger/budget/rate/GateState。
9. **ABSTAIN_SENSITIVITY**：COUPLING_SENSITIVE 或 UTILITY_SENSITIVE 均强制 action=PROBE、attempt_status=ABSTAIN_SENSITIVITY、safe_eligible=false；INDEPENDENT_REVIEW 是后续签名 control，不是 action token。仅新 epoch 下独立签署并由 manifest 绑定的新 mapper/coupling family 或效用族可解除。
10. **CONJUNCTIVE/INITIALIZE**：BUDGET_CAP、RATE_CAP、JOINT_GATE_FAIL 分别唯一映射为 action/attempt_status=ABSTAIN_BUDGET、ABSTAIN_RATE、ABSTAIN_CONFLICT；成功则 reason_code=ACCEPTANCE_COMPLETE、action=ACCEPT_CONTRIBUTION、attempt_status=ACCEPTED。只有 beta>0、rate slot 可用且 joint gate 通过才 ACTIVE 并消费首次 slot。
'@
$t = Replace-RegexOne $t $routePattern $routeReplacement 'main route table'

$algoPattern = '(?ms)^\*\*算法 2：单个候选的原子运行路径。\*\*\n\n1\..*?^7\..*?$'
$algoReplacement = @'
**算法 2：单个候选的原子运行路径。**

1. 从最新可串行化状态执行唯一 predictor 并冻结本次 CAS 读集/ReplayContext；验证 credential chain 与 RootIdentityManifest。失败按 REJECT_AUTH 结束；成功则冻结 TTL，并以 \(H(event_id,processing)\) 幂等提交一次 processing token。
2. 递归解析 canonical root/class redirect 与 expiry；RETIRED 唯一走 RETIRED_LATE_AUDIT。其余对象运行 sealed outer contract；outer failure 与 exact duplicate 分别终止于 REJECT_SCHEMA/QUARANTINED 与 DUPLICATE_AUDIT。
3. 对 outer-valid、非重复候选运行 SourceAdapter；MAPPING_* 唯一映射 ABSTAIN_MAPPING。随后按已解析对象类型，以同一 sealed bundle 的认证 \(z_r\) 运行 root/class-level \(J_o/J_{merge}\)、ScopeClosure 和一次 root-global joint 编译。
4. 以 candidate、PCR、OLR、完整 ACTIVE root/class 生成图和高阶超边构造带 generator/hash 与 witness/hash 的 SetwiseEligibilityCertificate；missing/stale/UNKNOWN/BLOCKED 强制 ABSTAIN_RELATION。
5. 仅对集合 ELIGIBLE 的候选选择 admission/supersede 路由，依次预留 principal/root/target commitment、queue、acceptance slot，折扣一次 root-global valuation并计算 joint gate；coupling/utility 翻转走 ABSTAIN_SENSITIVITY。
6. 以完整 CAS 读集原子提交 registry、ledger、belief、budget、rate、gate、lifecycle 与 latch；任何读集变化释放未提交预留，从本算法第 1 步读取最新状态重算。已提交 processing token 由同一 event-resource key 命中，绝不二次收费。
7. replay/latch/ISCM 与 mandatory control 的状态必须在同一 CAS 内先于 ActionState 计算；不可用、锁存、ABSTAIN_SENSITIVITY 或 mandatory replay 未闭合时禁止 SAFE_ELIGIBLE。
'@
$t = Replace-RegexOne $t $algoPattern $algoReplacement 'main algorithm 2'

$t = Replace-One $t '`ActionTruthManifest` 由独立过程安全团队在 test seed 前签署每个 tick 的可接受行动集合 \(\mathcal A_i^*(t)\)、可接受 barrier-demand 向量集合和禁止行动；仅当输出属于签署集合时 \(L_{act}=0\)。' '`ActionTruthRuleManifest` 由独立过程安全团队在任何 test seed 生成前签署动作生成规则、允许集合语义、deadline、分歧裁决与 scorer code/hash；每个 test bundle 的 `ActionTruthManifest` 只能由该冻结规则自动生成，生成后在方法容器启动前由两名独立复核者双签审计，禁止看方法输出后改写。仅当输出属于签署集合时 \(L_{act}=0\)。' 'main ActionTruth timing'

$t = Replace-One $t '对两个共同主效应报告单侧 97.5% 上置信界（等价于双侧 95% 区间的上端点）。两上界均小于 0 且资格门通过，才支持统计改善；两上界进一步小于各自 \(-\delta\)，才支持达到业务幅度。主资格同时约束 unsafe-SAFE 组件、方法失败组件、良性 SAFE availability、误升级、拒判、barrier calibration/demand sensitivity、P99、查询/更新预算和 SAFE invariant。' '对两个共同主效应报告单侧 97.5% 上置信界（等价于双侧 95% 区间的上端点）。上界小于 0 只报告名义统计方向；C-System 只有在两上界均小于各自预签 \(-\delta\)，且 unsafe-SAFE、方法失败、miss mass、良性 SAFE availability、误升级、拒判、barrier calibration/demand sensitivity、P99、查询/更新预算和 SAFE invariant 的全部 no-harm/资格门通过时才成立。' 'main C-System threshold'
$t = Replace-One $t '层级固定为：A−G* 系统主张与组件 no-harm → A−\(A^{-Topo}\) hazard–barrier 增量 → \(M_4-M_3\) 预算机制增量 → 其余机制与表示层。' '层级固定为：Q（C-Audit 与 C-Conserve-Inv）→ A−G* 的 C-System 与组件 no-harm → A−\(A^{-Topo}\) 的 C-HB → A 对 A^-Ledger/A^-Scope 的 C-Conserve-Benefit → \(M_4-M_3\) 的 C-Budget → 其余机制与表示层。' 'main gate order'

Write-Utf8 $mainPath $t

# -----------------------------------------------------------------------------
# Supplement S1
# -----------------------------------------------------------------------------
$t = Read-Utf8 $s1Path

$old = @'
| C-Audit | SafetyArtifactIR/SourceAdapter 正负性质测试与 total disposition | 不得声称安全工件编译正确 |
| C-Conserve | root/view、duplicate、version、merge、retire、replay 不变量 | 任一重复贡献即核心实现不符合规范 |
| C-System | 仅引用 v6.7 的系统级确认性 gate | 未实验时保持 PENDING-EMPIRICAL |
| C-HB | 与保持同一 demand clock 的拓扑消融绑定 | 未通过则降级为应用域 |
| C-Budget | M4−M3 机制性质与 v6.7 estimand | 未通过不得进入核心贡献 |
'@
$new = @'
| C-Audit | SafetyArtifactIR/SourceAdapter 正负性质测试与 total disposition | 不得声称安全工件编译正确 |
| C-Conserve-Inv | root/view、duplicate、version、merge、retire、replay 不变量 | 任一重复贡献即核心实现不符合规范并阻断性能检验 |
| C-System | 仅引用 v6.7 的系统级确认性 gate | 未实验时保持 PENDING-EMPIRICAL |
| C-HB | 与保持同一 demand clock 的拓扑消融绑定 | 未通过则降级为应用域 |
| C-Conserve-Benefit | A 对 A^-Ledger/A^-Scope 的经验机制增量 | 失败不否定 C-Conserve-Inv，但不得声称性能收益 |
| C-Budget | M4−M3 机制性质与 v6.7 estimand | 未通过不得进入核心贡献 |
'@
$t = Replace-One $t $old $new 'S1 claim table'

$t = Replace-One $t 'RootIdentityManifest 唯一绑定 credential_subject、acquisition UUID/root_epoch、root_type、TTL_policy_id、schema_version 与 acquisition_manifest_hash。' 'RootIdentityManifest 唯一绑定 credential_subject、acquisition UUID/root_epoch、root_type、TTL_policy_id、schema_version 与 acquisition_manifest_hash；签名 AcquisitionManifest schema 必须进一步包含 Eventifier id/version/hash、可信 clock domain、区间 [t_start,t_end)、causal_boundary_id/hash、原始采集身份和分段证据。TTL 不是观测有效区间。' 'S1 root manifest fields'

$t = Replace-One $t '最小身份认证只验证 credential chain 与 \(M\) 签名；成功即 identity-valid，并以 \(M.root\_type\) 冻结 registry TTL。' '最小身份认证只验证 credential chain 与 \(M\) 签名；失败 reason_code 只取 CREDENTIAL_CHAIN_INVALID 或 ROOT_IDENTITY_MANIFEST_SIGNATURE_INVALID，唯一 action=REJECT_AUTH，只写 QuarantineLog，不建 Registry、不写 attempt、不冻结 TTL且不收费。成功才称 identity-valid，并以 \(M.root\_type\) 冻结 registry TTL。' 'S1 minimal auth contract'
$t = Replace-One $t 'outer validator 必须机械断言 IngressEnvelope 与 seal 的 \(root\_type=M.root\_type\)、\(root\_identity\_manifest\_hash=H(M)\)、\(schema\_version=M.schema\_version\)、\(acquisition\_manifest\_hash=M.acquisition\_manifest\_hash\)，并对实际 acquisition manifest \(A\) 断言 \(H(A)=M.acquisition\_manifest\_hash\)。' 'outer validator 必须机械断言 IngressEnvelope 与 seal 的 \(root\_type=M.root\_type\)、\(root\_identity\_manifest\_hash=H(M)\)、\(schema\_version=M.schema\_version\)、\(acquisition\_manifest\_hash=M.acquisition\_manifest\_hash\)，并对实际 AcquisitionManifest \(A\) 断言 \(H(A)=M.acquisition\_manifest\_hash\)，再按 schema 验证 Eventifier id/version/hash、可信 clock、区间、causal boundary、原始采集身份和分段证据。' 'S1 outer root binding'
$t = Replace-One $t '密码学或 identity-binding 失败只走 REJECT_SCHEMA/QUARANTINED。' '通过 minimal auth 后的 envelope/seal/record/artifact 密码学或 identity-binding 失败只走 REJECT_SCHEMA/QUARANTINED；minimal-auth 本身的两类失败只走 REJECT_AUTH/NO_ATTEMPT。' 'S1 auth/outer split'

$t = Replace-One $t '确认性主分析优先使用在独立 pilot 中联合校准的 root-level mapper \(f_o(\{x_r,q_r\}_r,c)\to\mathcal V_o\)。' '确认性主分析优先使用在独立 `D_mapper_cal` 中联合校准、并在 `D_mapper_qual` 资格集冻结的 root-level mapper \(f_o(\{z_r\}_r,c)\to\mathcal V_o\)；\(z_r\) 是 SourceAdapter 已认证输出，mapper 不得绕过 adapter 重读 raw input。' 'S1 mapper interface'

$t = Replace-One $t 'attempt_status 取 QUARANTINED、ABSTAIN_MAPPING、ABSTAIN_COMPLEXITY、ABSTAIN_RATE、ABSTAIN_RELATION、ABSTAIN_CONFLICT、ABSTAIN_BUDGET、SUPERSEDE_PRINCIPAL_BLOCKED、TARGET_SCOPE_CHANGE_BLOCKED 或 ACCEPTED。' 'attempt_status 取 QUARANTINED、ABSTAIN_MAPPING、ABSTAIN_COMPLEXITY、ABSTAIN_RATE、ABSTAIN_RELATION、ABSTAIN_SENSITIVITY、ABSTAIN_CONFLICT、ABSTAIN_BUDGET、SUPERSEDE_PRINCIPAL_BLOCKED、TARGET_SCOPE_CHANGE_BLOCKED 或 ACCEPTED；minimal-auth REJECT_AUTH 与 DUPLICATE_AUDIT 不写 RootRegistry attempt。' 'S1 attempt enum'

$t = Replace-One $t '2. 验证 credential chain 与 RootIdentityManifest signature；失败则 QuarantineLog+REJECT。成功即 identity-valid，以 authenticated root_type 在 outer validation 前新建/读取 Registry、冻结 TTL，并用 \(H(event\_id,processing\_token)\) 幂等收取一次不可退 processing token。retired、outer-invalid、mapping/compiler 失败事件均收费；CAS retry 不重复收费。' '2. 验证 credential chain 与 RootIdentityManifest signature；失败分别以 CREDENTIAL_CHAIN_INVALID 或 ROOT_IDENTITY_MANIFEST_SIGNATURE_INVALID 写 QuarantineLog，唯一 action=REJECT_AUTH、attempt_status=NO_ATTEMPT，不建 Registry、不冻结 TTL且不收费。成功即 identity-valid，以 authenticated root_type 在 outer validation 前新建/读取 Registry、冻结 TTL，并用 \(H(event\_id,processing\_token)\) 幂等收取一次不可退 processing token。identity-valid 的 retired、outer-invalid、mapping/compiler 失败事件均收费；CAS retry 不重复收费。' 'S1 algorithm auth'

$t = Replace-One $t '6. 非重复候选先运行 SourceAdapter mapping。certificate 缺失/过期、validity-domain 超界、drift/OOD 或其他映射失败分别记录 MAPPING_CERTIFICATE_INVALID、MAPPING_VALIDITY_DOMAIN_EXCEEDED、MAPPING_DRIFT_DETECTED 或 MAPPING_UNKNOWN；action 与 attempt_status 均为 ABSTAIN_MAPPING，不生成 typed claim；结束。' '6. 非重复候选先运行 SourceAdapter mapping。certificate 缺失/过期、validity-domain 超界、drift/OOD 或其他映射失败分别记录 MAPPING_CERTIFICATE_INVALID、MAPPING_VALIDITY_DOMAIN_EXCEEDED、MAPPING_DRIFT_DETECTED 或 MAPPING_UNKNOWN；action 与 attempt_status 均为 ABSTAIN_MAPPING，不生成 \(z_r\)。Registry 只追加 attempt，并将 never-committed 条目置 NONCONTRIBUTING；belief/ledger/budget/rate/GateState 不变；结束。' 'S1 mapping registry'
$t = Replace-One $t 'mapping VALID 后推进 highest_outer_valid_attempt_version，再按 class_record 对全 class 运行 \(J_{merge}\)，非 class 运行 \(J_o\) 与 ScopeClosure。' 'mapping VALID 后推进 highest_outer_valid_attempt_version，再按 class_record 对同一 sealed bundle 的认证 \(z_r\) 运行 \(J_{merge}\)，非 class 运行 \(J_o\) 与 ScopeClosure。' 'S1 mapper input'
$t = Replace-One $t '变化则释放未提交预留并从第 6 步重算。' '变化则释放未提交预留，从第 1 步读取最新可串行化状态并重新执行 predictor、minimal-auth、redirect、outer、mapping 与后续步骤；已提交 processing token 由同一 event-resource key 命中，不二次收费。' 'S1 CAS retry'

$t = Replace-One $t '候选 target_scope_contract 必须与首次集合逐项相同，否则 TARGET_SCOPE_CHANGE_BLOCKED；' '候选 target_scope_contract 必须与首次集合逐项相同，否则 reason_code=TARGET_SCOPE_CHANGE、action=TARGET_SCOPE_CHANGE_BLOCKED、attempt_status=TARGET_SCOPE_CHANGE_BLOCKED；' 'S1 target scope triple'
$t = Replace-One $t '每个新增主体须全额预留旧 beta，不足则 SUPERSEDE_PRINCIPAL_BLOCKED。' '每个新增主体须全额预留旧 beta；不足时 reason_code=SUPERSEDE_PRINCIPAL_CAP、action=SUPERSEDE_PRINCIPAL_BLOCKED、attempt_status=SUPERSEDE_PRINCIPAL_BLOCKED。' 'S1 principal triple'

$t = Replace-One $t '\(\mathsf{repr}_o\) 是其精确因子化表示；manifest 证明每个胜出 input slot 恰好使用一次。v20 的 \(\mathcal V_o\) 必须由 S1.2 的共享潜变量 compiler 逐区间构造；typing/mapping 只提供同一 sealed bundle_version 内的签名嵌套焦元日程和约束，唯一无权重 target_scope_contract 集合来自 seal，不能跨版本拼槽、按 view 累加权重，或先产生若干场景 BPA 再以 Dempster、tensor product、独立乘法或逐场景归一化拼接。' '\(\mathsf{repr}_o\) 是其精确因子化表示；manifest 证明每个胜出 input slot 恰好使用一次。v20.1 的主路径必须由冻结 RootLevelMapperManifest 约束的 \(J_o(\{z_r\})\) 产生唯一 \(\mathcal V_o\)；若主 mapper 不可用且协议预签，才对冻结 coupling family \(\mathcal K_o\) 计算包络。S1.2 的共享潜变量 compiler 只是其中一个具名敏感性模型，绝不是主路径强制项。唯一无权重 target_scope_contract 来自 seal，不能跨版本拼槽、按 view 累加权重，或先产生若干场景 BPA 再独立拼接。' 'S1 stale shared-u mandate'

$t = Replace-One $t 'credential chain/RootIdentityManifest signature failure 只能 minimal-auth QuarantineLog+REJECT；envelope/seal/record/artifact signature 或 identity-binding failure 只能 outer REJECT_SCHEMA，' 'credential chain/RootIdentityManifest signature failure 只能 minimal-auth QuarantineLog、action=REJECT_AUTH、attempt_status=NO_ATTEMPT 且不收费；envelope/seal/record/artifact signature 或 identity-binding failure 只能 outer REJECT_SCHEMA/QUARANTINED，' 'S1 auth property'

$t = Replace-One $t 'NormativeReleaseManifest 至少绑定 main-v20.1/S1-v20.1/S2-v20.1/v6.7、IR schema、compiler、failure-code registry、SafetyArtifactIR、OperationalSafetyArtifact 和分析容器。' 'NormativeReleaseManifest 的最低字段必须与 S2.0 的 canonical JSON Schema 逐项相同，绑定 main-v20.1/S1-v20.1/S2-v20.1/v6.7、ClaimRegister、IR/schema/compiler、RootIdentity/AcquisitionManifest schema、Eventifier、SourceAdapter/RootLevelMapper/coupling-family registries、SetwiseEligibilityGenerator、SafetyArtifactIR、OperationalSafetyArtifact、Method/ArmFrame、Seed/Allocation/Test manifests、分析容器和依赖 DAG。' 'S1 manifest contract'

$t = Replace-One $t '四者的强制 action/attempt_status 均为 ABSTAIN_MAPPING，不得生成可合取 claim。共享 \(u\) 只是具名 coupling 敏感性模型；主分析使用联合校准 root-level mapper 或冻结 coupling family 包络。' '四者的强制 action/attempt_status 均为 ABSTAIN_MAPPING，不得生成 \(z_r\)。SourceAdapter 输出 schema 与 RootLevelMapperManifest 的允许输入 schema 必须逐项匹配；共享 \(u\) 只是具名 coupling 敏感性模型，主分析使用联合校准 root-level mapper 或冻结 coupling family 包络。COUPLING_SENSITIVE/UTILITY_SENSITIVE 唯一映射 action=PROBE、attempt_status=ABSTAIN_SENSITIVITY；独立复核是后续 control。' 'S1 mapping property'

$t = Replace-One $t '对候选 \(o\)、活动根集合 \(A_k\) 和上下文 \(c\)，生成完整派生图、观测生成图、物理潜变量图和高阶超边，验证 SetwiseEligibilityCertificate：' '对候选 \(o\)、活动根集合 \(A_k\) 和上下文 \(c\)，冻结 generator version/hash、算法语义版本、cap/policy hash 和 adjudication-policy hash，生成完整派生图、观测生成图、物理潜变量图、高阶超边及最小见证子图/hash，验证 SetwiseEligibilityCertificate：' 'S1 setwise fields'

Write-Utf8 $s1Path $t

# -----------------------------------------------------------------------------
# Supplement S2
# -----------------------------------------------------------------------------
$t = Read-Utf8 $s2Path

$t = Replace-One $t '`NormativeReleaseManifest` 至少包含：`release_id`、`main_version/hash`、`S1_version/hash`、`S2_version/hash`、`experiment_version/hash`、`SafetyArtifactIR_schema_version/hash`、`compiler_version/hash`、`failure_code_registry_hash`、`OperationalSafetyArtifact_hash`、`analysis_container_hash` 与有向依赖边。' '`NormativeReleaseManifest` 的 canonical JSON Schema 至少包含：`release_id`；`main/S1/S2/experiment version+sha256`；`ClaimRegister_sha256`；`SafetyArtifactIR_schema version+sha256` 与 `SafetyArtifactIR_sha256`；`compiler version+sha256`；`failure_code_registry_sha256`；`RootIdentityManifest_schema_sha256`；`AcquisitionManifest_schema_sha256`；`Eventifier version+sha256`；`SourceAdapterRegistry_sha256`；`RootLevelMapperRegistry_sha256`；`CouplingFamilyRegistry_sha256`；`SetwiseEligibilityGenerator version+sha256`；`OperationalSafetyArtifact_sha256`；`MethodRegistry_sha256`；`ArmFrameMatrix_sha256`；`SeedManifest_sha256`；`AllocationManifest_sha256`；`TestManifest_sha256`；`analysis_container_sha256` 与有向依赖边。设计阶段允许值为 `PENDING-HASH`，但任一 PENDING 字段均阻止 confirmation seal/test 解封。' 'S2 canonical manifest'

$t = Replace-One $t 'ClaimRegister 必须包含 C-Audit、C-Conserve、C-System、C-HB 与 C-Budget，' 'ClaimRegister 必须包含 C-Audit、C-Conserve-Inv、C-System、C-HB、C-Conserve-Benefit 与 C-Budget，' 'S2 claim IDs'

$t = Replace-One $t '且 \(M\) 唯一绑定 credential_subject、acquisition UUID/root_epoch、root_type、TTL_policy_id、schema_version 与 acquisition_manifest_hash。' '且 \(M\) 唯一绑定 credential_subject、acquisition UUID/root_epoch、root_type、TTL_policy_id、schema_version 与 acquisition_manifest_hash；被 hash 的 AcquisitionManifest 必须按冻结 schema 包含 Eventifier id/version/hash、可信 clock domain、区间 [t_start,t_end)、causal_boundary_id/hash、原始采集身份与分段证据。TTL 仅是 registry 服务寿命。' 'S2 root fields'
$t = Replace-One $t '最小身份认证只验证 credential chain 与 \(M\) 的 signature；成功即称 identity-valid，并立即以可信 \(\tau\) 和 \(M.root\_type\) 注册 TTL，即使后续 outer validation 失败也不得重置。' '最小身份认证只验证 credential chain 与 \(M\) 的 signature；失败 reason_code 只取 CREDENTIAL_CHAIN_INVALID 或 ROOT_IDENTITY_MANIFEST_SIGNATURE_INVALID，唯一 action=REJECT_AUTH，只写 QuarantineLog，attempt_status=NO_ATTEMPT，不建 Registry、不冻结 TTL且不收费。成功才称 identity-valid，并立即以可信 \(\tau\) 和 \(M.root\_type\) 注册 TTL，即使后续 outer validation 失败也不得重置。' 'S2 minimal auth'
$t = Replace-One $t '并对实际 acquisition manifest \(A\) 验证 \(H(A)=M.acquisition\_manifest\_hash\)。' '并对实际 AcquisitionManifest \(A\) 验证 \(H(A)=M.acquisition\_manifest\_hash\)，再验证其 Eventifier/clock/interval/causal-boundary/acquisition 字段符合冻结 schema。' 'S2 acquisition validation'
$t = Replace-One $t '任一密码学或 identity-binding 失败只映射 REJECT_SCHEMA/QUARANTINED。' '通过 minimal auth 后的任一 envelope/seal/record/artifact 密码学或 identity-binding 失败只映射 REJECT_SCHEMA/QUARANTINED；minimal-auth 本身只映射 REJECT_AUTH/NO_ATTEMPT。' 'S2 auth split'

$t = Replace-One $t '对其余 raw claims 单次运行冻结的 root/class-level mapper \(J_{merge}\)；共享潜变量交集只作为具名敏感性模型，' '对其余 SourceAdapter 已认证输出 \(z_r\) 单次运行 RootLevelMapperManifest 冻结的 root/class-level mapper \(J_{merge}\)；mapper 不得绕过 adapter 重读 raw input，共享潜变量交集只作为具名敏感性模型，' 'S2 merge mapper input'

$t = Replace-One $t '变化则释放未提交预留并从路由起点重算。' '变化则释放未提交预留，从事务第 1 步读取最新状态并重新执行 predictor、minimal-auth、redirect、outer、mapping 与后续步骤；已提交 processing token 由 event-resource key 命中，不二次收费。' 'S2 CAS retry'

$old = '事务顺序固定为：预测；最小身份认证、冻结 TTL 并以 event_id 幂等提交一次 processing token；解析 retired/class redirect；RETIRED_LATE_AUDIT 或 outer identity/seal 验证；outer-valid 后精确去重；SourceAdapter mapping；按对象类型运行 root/class-level mapper \(J_o/J_{merge}\) 与 ScopeClosure；用当前 candidate、ACTIVE roots 和 context 重建 SetwiseEligibilityCertificate；仅 ELIGIBLE 才选 admission/supersede 路由并预留主体/root/每个 target 的完整 beta、queue 和 acceptance slot；只折扣一次 root-global valuation；计算 joint gate/GateState。retired、outer-invalid、mapping/compiler 失败事件均收一次 processing token，CAS retry 不重复。'
$new = '事务顺序固定为：读取最新状态并预测；最小身份认证，失败以 REJECT_AUTH/NO_ATTEMPT 结束且不收费；成功才冻结 TTL并以 event_id 幂等提交一次 processing token；解析 retired/class redirect；RETIRED_LATE_AUDIT 或 outer identity/seal 验证；outer-valid 后精确去重；SourceAdapter 生成认证 \(z_r\)；按对象类型运行 RootLevelMapperManifest 冻结的 \(J_o/J_{merge}\) 与 ScopeClosure；用当前 candidate、ACTIVE roots、context 和冻结 generator 重建 SetwiseEligibilityCertificate；仅 ELIGIBLE 才选 admission/supersede 路由并预留主体/root/每个 target 的完整 beta、queue 和 acceptance slot；只折扣一次 root-global valuation；计算 joint gate/GateState；同一 CAS 内先更新 replay/latch/ISCM 再计算 ActionState。identity-valid 的 retired、outer-invalid、mapping/compiler 失败事件均收一次 processing token，CAS retry 不重复。'
$t = Replace-One $t $old $new 'S2 transaction order'

$t = Replace-One $t '每个 `SourceAdapterManifest` 至少包含：`adapter_id/version/hash`、`source_type`、`input_schema_hash`、`training_data_hash`、`calibration_data_hash`、`calibration_target/error_bound`、`validity_domain`、`missing_policy`、`lateness_policy`、`OOD_or_drift_detector/hash/threshold`、`focal_schedule_schema`、`within_root_coupling_id`、`failure_action` 与签名。adapter 只输出 typed focal-set schedule、calibration certificate 和 validity status。' '每个 `SourceAdapterManifest` 至少包含：`adapter_id/version/hash`、`source_type`、`input_schema_hash`、`training_data_hash`、`calibration_data_hash`、`calibration_target/error_bound`、`validity_domain`、`missing_policy`、`lateness_policy`、`OOD_or_drift_detector/hash/threshold`、`typed_feature_schema_hash`、可选 `focal_schedule_schema`、`within_root_coupling_id`、`failure_action` 与签名。adapter 只输出认证 \(z_s=(typed\ feature,optional\ focal\ schedule,certificate,validity)\)。`RootLevelMapperManifest` 必须冻结允许 adapter/output schema 集、输入排序、`D_mapper_cal/D_mapper_qual` hashes、联合校准目标/误差、适用域、代码/容器 hash 和 failure policy；\(J_o/J_{merge}\) 只消费同一 sealed bundle 的 \(z_s\)，不得重读未认证 raw input。' 'S2 mapping manifest'

$t = Replace-One $t '四者均强制 action=`ABSTAIN_MAPPING`、attempt_status=`ABSTAIN_MAPPING`，不得生成 typed claim。within-root coupling 是版本化假设；主分析使用联合校准 root-level mapper 或冻结 coupling-family 包络，SAFE/排序翻转返回 `COUPLING_SENSITIVE` 并开启新 epoch 才能解除。' '四者均强制 action=`ABSTAIN_MAPPING`、attempt_status=`ABSTAIN_MAPPING`，不得生成 \(z_s\)。within-root coupling 是版本化假设；主分析使用联合校准 root-level mapper 或冻结 coupling-family 包络，SAFE/排序翻转返回 `COUPLING_SENSITIVE`，唯一 action=PROBE、attempt_status=ABSTAIN_SENSITIVITY，并在新 epoch 才能解除。' 'S2 mapping routes'

$t = Replace-One $t '证书字段至少包含：`candidate_root`、`active_root_set_hash`、`context_hash`、`root_class_map_hash`、`derivation_graph_hash`、`observation_generation_graph_hash`、`physical_latent_graph_hash`、`higher_order_hyperedge_hash`、`modeled_shared_causes`、`unmodeled_shared_causes`、`conditional_structure_claims`、`registry_completeness_attestation`、`valid_from/to`、`decision`、`reason_codes` 和签名。' '证书字段至少包含：`candidate_root`、`active_root_set_hash`、`context_hash`、`root_class_map_hash`、`generator_version/hash`、`algorithm_semantics_version`、`cap_policy_hash`、`adjudication_policy_hash`、`derivation_graph_hash`、`observation_generation_graph_hash`、`physical_latent_graph_hash`、`higher_order_hyperedge_hash`、`witness_subgraph/hash`、`modeled_shared_causes`、`unmodeled_shared_causes`、`conditional_structure_claims`、`registry_completeness_attestation`、`valid_from/to`、`decision`、`reason_codes` 和签名。' 'S2 certificate fields'

$t = Replace-One $t '- `MAPPING_CERTIFICATE_INVALID`' '- `CREDENTIAL_CHAIN_INVALID` / `ROOT_IDENTITY_MANIFEST_SIGNATURE_INVALID` → REJECT_AUTH / NO_ATTEMPT`n- `ROOT_TYPE_BINDING_INVALID` / `ROOT_IDENTITY_BINDING_INVALID` / `BUNDLE_SEAL_INVALID` / `ENVELOPE_EQUIVOCATION` → REJECT_SCHEMA / QUARANTINED`n- `MAPPING_CERTIFICATE_INVALID`' 'S2 failure list auth'

$old = '路由合同唯一化如下：四个 MAPPING_* reason_code 均强制 action=ABSTAIN_MAPPING、attempt_status=ABSTAIN_MAPPING；该 action 不生成 typed claim、不进入集合资格或融合。全部 SETWISE_* 强制 action=ABSTAIN_RELATION、attempt_status=ABSTAIN_RELATION。COUPLING_SENSITIVE 与 UTILITY_SENSITIVE 均强制 action=PROBE/INDEPENDENT_REVIEW、safe_eligible=false；只有新 epoch 下独立签署的 mapper/coupling family 或效用族才能解除。never-committed 条目置 NONCONTRIBUTING，committed lifecycle/token 保持；各路由均按预签严重度 LATCH_SET。'
$new = '路由合同唯一化如下：minimal-auth 两个 reason 只写 QuarantineLog，action=REJECT_AUTH、attempt_status=NO_ATTEMPT且不收费；outer reason 强制 action=REJECT_SCHEMA、attempt_status=QUARANTINED；四个 MAPPING_* 强制 action/attempt_status=ABSTAIN_MAPPING；COMPILER_CAP_EXCEEDED 强制 ABSTAIN_COMPLEXITY；MAPPING_INVALID、TARGET_SCOPE_CONFLICT、STRUCTURAL_CONSTRAINT_FAIL、NO_EVIDENCE、INTRABUNDLE_DISCORD 与全部 SETWISE_* 强制 action/attempt_status=ABSTAIN_RELATION；COUPLING_SENSITIVE/UTILITY_SENSITIVE 强制 action=PROBE、attempt_status=ABSTAIN_SENSITIVITY，INDEPENDENT_REVIEW 是后续 control；BUDGET_CAP、RATE_CAP、JOINT_GATE_FAIL 分别映射 ABSTAIN_BUDGET、ABSTAIN_RATE、ABSTAIN_CONFLICT；SUPERSEDE_PRINCIPAL_CAP 映射 SUPERSEDE_PRINCIPAL_BLOCKED；TARGET_SCOPE_CHANGE 映射 TARGET_SCOPE_CHANGE_BLOCKED；ACCEPTANCE_COMPLETE 映射 action=ACCEPT_CONTRIBUTION、attempt_status=ACCEPTED。除 REJECT_AUTH/DUPLICATE_AUDIT/RETIRED_LATE_AUDIT 外，每个候选终止分支必须追加且仅追加一个 attempt。'
$t = Replace-One $t $old $new 'S2 full route triples'

Write-Utf8 $s2Path $t

# -----------------------------------------------------------------------------
# Experiment protocol v6.7
# -----------------------------------------------------------------------------
$t = Read-Utf8 $expPath

$t = Replace-One $t 'v20.1、S1 v20.1、S2 v20.1 与本协议 v6.7 必须由同一 `NormativeReleaseManifest` 绑定。' 'v20.1、S1 v20.1、S2 v20.1 与本协议 v6.7 必须由同一 `NormativeReleaseManifest` 绑定；其最低字段逐项采用 S2.0 canonical JSON Schema，并包含 ClaimRegister、Eventifier、mapper/coupling/setwise、Method/ArmFrame、Seed/Allocation/Test manifests 的 hash。' 'exp manifest binding'

$old = @'
| Q | C-Audit / C-Conserve | 实现符合 v20.1；无重复根贡献、标签泄漏、版本/重放漂移 | 任一 P0-C/P0-V 失败则不进入性能检验 |
| 1 | C-System | A 相对冻结 G* 同时改善危险决策与行动及时性 | 两个共同主终点和两个组件 no-harm 全部通过 |
| 2 | C-HB | 显式 hazard–barrier 语义具有增量 | A 对 A^-Topo 的预签 estimand 通过；否则降级为应用域 |
| 3 | C-Conserve | lifecycle 治理相对 lineage-only/无账本变体降低重复贡献与 false-safe | 对抗轨迹不变量 + 决策指标全部通过 |
| 4 | C-Budget | 多轴预算相对 M3 有独立机制价值 | M4−M3 的预签 SESOI/no-harm/资源门通过 |
'@
$new = @'
| Q | C-Audit / C-Conserve-Inv | 实现符合 v20.1；无重复根贡献、标签泄漏、版本/重放漂移 | 任一 P0-C/P0-V 失败则不进入性能检验 |
| 1 | C-System | A 相对冻结 G* 同时达到危险决策与行动及时性的预签改善幅度 | 两个共同主终点均越过 SESOI，且全部组件 no-harm/资格门通过 |
| 2 | C-HB | 显式 hazard–barrier 语义具有增量 | A 对 A^-Topo 的预签 estimand 通过；否则降级为应用域 |
| 3 | C-Conserve-Benefit | lifecycle 治理相对 lineage-only/无账本变体降低重复贡献与 false-safe | 对抗轨迹、决策、可用性 estimand 全部通过；失败不撤销 C-Conserve-Inv |
| 4 | C-Budget | 多轴预算相对 M3 有独立机制价值 | M4−M3 的预签 SESOI/no-harm/资源门通过 |
'@
$t = Replace-One $t $old $new 'exp claim gates'

$t = Replace-One $t '每层至少正交操纵：' '每层先按预签分布抽样 operating mode、barrier configuration 和 registered CCF level，并满足冻结最低边际覆盖；随后至少正交操纵：' 'exp axes alignment'

$t = Replace-One $t '数据命名空间完全不重叠：`D_shakedown`、`D_train/tune`、`D_select`、`D_pilot_fit`、`D_pilot_heldout`、`D_test`、`D_external`。' '数据命名空间完全不重叠：`D_shakedown`、`D_train/tune`、`D_mapper_cal`、`D_mapper_qual`、`D_select`、`D_pilot_fit`、`D_pilot_heldout`、`D_test`、`D_external`。RootLevelMapper 只在 D_mapper_cal 联合校准，并在 D_mapper_qual 一次冻结输入 schema、coverage/error、适用域和 coupling sensitivity；这两集不进入 G* 选择、pilot 功效核或 test。' 'exp mapper split'

$t = Replace-One $t '每个 bundle 的 `ActionTruthManifest` 由两名独立过程安全复核者在看方法输出前签署，记录：可接受动作集合、禁止动作、deadline、屏障状态向量、top-event 接近度、truth provenance 和分歧裁决。' '任何 test seed 生成前，独立过程安全团队先签署 `ActionTruthRuleManifest`，冻结可接受集合生成规则、禁止动作、deadline、屏障状态语义、top-event 接近度、truth provenance、分歧裁决与 scorer code/hash。每个 bundle 的 `ActionTruthManifest` 只能由该规则自动生成，并在方法容器启动前由两名独立复核者双签审计；不得看方法输出后修改。' 'exp ActionTruth timing'

$t = Replace-One $t '5. Qualification gate 全部通过。' '5. unsafe-SAFE、方法失败、miss mass、良性 SAFE availability、误升级、拒判、barrier calibration/demand sensitivity、P99、query/update budget 与 SAFE invariant 的全部冻结 no-harm/Qualification gate 通过。' 'exp qualification list'

$t = Replace-One $t '- C-Conserve：每根有效贡献次数、false allow/false block、replay hash、过度置信与决策错误；' '- C-Conserve-Inv：每根有效贡献次数、replay/canonicalization hash 和全部 P0 性质测试；`n/a` 于经验优越性；`n- C-Conserve-Benefit：A−A^-Ledger/A^-Scope 的 false allow/false block、过度置信、决策错误和 availability；' 'exp conserve outcomes'

$t = Replace-One $t '每个标题级 claim 使用 IUT；claim 间固定序列。Gate 4 若包含多项预算 contrasts，须在 SAP 中列出完整 Holm family。所有置信限方向、alpha、尾部、bootstrap 次数、small-sample correction 和 missing/failure mapping 在 test 解封前冻结。' '每个标题级 claim 使用 IUT；claim 间固定序列 Q→C-System→C-HB→C-Conserve-Benefit→C-Budget。共同主终点均使用单侧 alpha=0.025 的上置信限；IUT 不再机械拆分 alpha。主估计冻结为按目标层权的 paired stratified bootstrap（20,000 次、SeedManifest 固定），稀有配对二元终点同时给 exact/score bound；若 pilot 触发预签 batch-ICC 阈值，则切换到 cluster-respecting bootstrap，阈值与实现必须在 test seal 前写入 SAP。Gate 4 若含多项预算 contrasts，使用预签 Holm family。任何 SESOI、no-harm margin、层权、small-sample correction 或 missing/failure mapping 为 PENDING 时，NormativeReleaseManifest 不得由 PENDING-HASH 升为 confirmable。' 'exp fixed inference skeleton'

$t = Replace-One $t '1. `NormativeReleaseManifest-v20.1-v6.7.json`；' '1. `NormativeReleaseManifest-v20.1-v6.7.json`（字段逐项符合 S2.0 canonical schema，confirmation 前无 PENDING-HASH）；' 'exp manifest deliverable'

Write-Utf8 $expPath $t

Write-Output 'v20.1/S1/S2/v6.7 consistency patch applied.'
