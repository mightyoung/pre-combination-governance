param([Parameter(Mandatory=$true)][string]$Workspace)

$ErrorActionPreference = 'Stop'
$utf8 = [System.Text.UTF8Encoding]::new($false)

function Replace-Exact {
    param([string]$Source, [string]$Old, [string]$New, [string]$Label)
    $count = ([regex]::Matches($Source, [regex]::Escape($Old))).Count
    if ($count -ne 1) { throw "Replacement '$Label' expected once, found $count" }
    return $Source.Replace($Old, $New)
}

# S1
$s1Path = Join-Path $Workspace '补充材料S1-v20.1-组合前治理证明与性质测试.md'
$s1 = [System.IO.File]::ReadAllText($s1Path, [System.Text.Encoding]::UTF8)
$s1 = Replace-Exact $s1 '# 补充材料 S1 v20：组合前治理证明、运行不变量与性质测试' '# 补充材料 S1 v20.1：组合前治理证明、运行不变量与性质测试' 's1-title'
$s1 = Replace-Exact $s1 @'
> 本材料与主文 v20、S2 v20 和实验协议 v6.5 由同一 NormativeReleaseManifest 绑定。S1 不能覆盖主文或 S2；任一语义冲突、版本不一致或 hash 不一致均使整个 release 失效。尚未生成正式 package hash 的条目保持 PENDING-HASH，不得执行确认性 test。
'@ @'
> 本材料与主文 v20.1、S2 v20.1 和实验协议 v6.7 由同一 NormativeReleaseManifest 绑定。S1 不能覆盖主文或 S2；任一语义冲突、版本不一致或 hash 不一致均使整个 release 失效。尚未生成正式 package hash 的条目保持 PENDING-HASH，不得执行确认性 test。

| Claim ID | S1 的规范证据 | 未闭合时的状态 |
| --- | --- | --- |
| C-Audit | SafetyArtifactIR/SourceAdapter 正负性质测试与 total disposition | 不得声称安全工件编译正确 |
| C-Conserve | root/view、duplicate、version、merge、retire、replay 不变量 | 任一重复贡献即核心实现不符合规范 |
| C-System | 仅引用 v6.7 的系统级确认性 gate | 未实验时保持 PENDING-EMPIRICAL |
| C-HB | 与保持同一 demand clock 的拓扑消融绑定 | 未通过则降级为应用域 |
| C-Budget | M4−M3 机制性质与 v6.7 estimand | 未通过不得进入核心贡献 |
'@ 's1-binding-claims'

$s1 = Replace-Exact $s1 '### S1.2.1 共享潜变量 compiler 的机械算法' @'
### S1.2.1 root-level mapping 合同与共享潜变量敏感性 compiler

确认性主分析优先使用在独立 pilot 中联合校准的 root-level mapper \(f_o(\{x_r,q_r\}_r,c)\to\mathcal V_o\)。其 view 集、校准目标、覆盖误差、适用域和版本哈希必须冻结。下述共享潜变量交集算法只定义一个具名 within-root coupling 敏感性模型；它不能仅凭“共用 \(u\)”获得一般保守性。若只能使用 per-view schedules，必须预注册 coupling family \(\mathcal K_o\)，对全部成员计算决策包络；SAFE 或方法排序发生翻转时返回 COUPLING_SENSITIVE 并阻断确认性 SAFE。
'@ 's1-mapper-heading'

$s1 = Replace-Exact $s1 @'
所有 claims 共用同一个 \(u\)，这等价于预注册的共单调随机集 coupling，而不是把同根 views 当独立样本。outer exact-envelope retry 不进入 compiler；即使两个不同 view 产生同一日程，集合交仍幂等。允许其他 compiler 属于未来版本，本确认性 v20 只实现本算法。
'@ @'
所有 claims 共用同一个 \(u\)，这等价于一个预注册的共单调随机集 coupling，而不是一般的保守性结论。outer exact-envelope retry 不进入 compiler；相同日程的重复 view 保持幂等。v20.1 的主确认性实现须使用联合校准 root-level mapper，或对冻结 \(\mathcal K_o\) 做包络；本算法仅作为敏感性臂。
'@ 's1-coupling-boundary'

$s1 = Replace-Exact $s1 @'
- append-only `attempt_status[version]`：QUARANTINED、ABSTAIN_COMPLEXITY、ABSTAIN_RATE、ABSTAIN_RELATION、ABSTAIN_CONFLICT、ABSTAIN_BUDGET、SUPERSEDE_PRINCIPAL_BLOCKED、TARGET_SCOPE_CHANGE_BLOCKED 或 ACCEPTED。
'@ @'
- append-only `attempt_log[(bundle_version,event_id)]`：每条含 reason_code、action 和 attempt_status；attempt_status 取 QUARANTINED、ABSTAIN_MAPPING、ABSTAIN_COMPLEXITY、ABSTAIN_RATE、ABSTAIN_RELATION、ABSTAIN_CONFLICT、ABSTAIN_BUDGET、SUPERSEDE_PRINCIPAL_BLOCKED、TARGET_SCOPE_CHANGE_BLOCKED 或 ACCEPTED。同一版本的后续事件不得覆盖既往 attempt。
'@ 's1-attempt-enum'

$oldAlgorithm = @'
2. 验证 credential chain 与 RootIdentityManifest signature；失败则 QuarantineLog+REJECT。成功即 identity-valid，以 manifest 的 authenticated root_type 在 outer validation 前新建/读取 Registry 并冻结 TTL；用 \(H(event\_id,processing\_token)\) 幂等收取不可退 processing token。
3. 递归解析 class/member redirect。若 representative lifecycle=RETIRED，则唯一走 RETIRED_LATE_AUDIT：只记安全审计，不写 attempt、不触发 latch、不运行 duplicate/outer/compiler；结束。
4. 对未退休对象，outer validator 独占检查 root_type/schema_version/acquisition manifest 与 RootIdentityManifest 的唯一绑定，以及 envelope/seal/assembler/winner/ABSENT/mapping-artifact signatures 与 hashes、字段类型、时间、schema、seq、seal/expected-slot equality 和版本规则。失败追加 QUARANTINED，既有 lifecycle/ledger 不变，按冻结码决定 latch；结束。outer 不检查焦元嵌套、target-scope 集合语义或 discord。
5. 仅对 outer-valid 对象，canonical root+bundle_version+envelope_hash 全同才走 DUPLICATE_AUDIT；相对预测态不融合，只更新 last_seen/retry_count/audit；结束。
6. outer-valid candidate 先推进 highest_outer_valid_attempt_version，再判 class_record：任一 member 包括 representative 只以暂存候选 map 对全 class 运行 \(J_{merge}\)，非 class 才运行 \(J_o\)。compiler cap/semantic failure 只写 attempt并结束，不推进 effective_bundle_version/member_version_map；committed lifecycle/token 保持。合法 joint 继续第 7 步。
7. 已见对象先硬检 class/root expires_at；到期只可能在系统优先 RETIRE 后成为第 3 步 audit。未到期时，non-class ever_committed=false/true 分别选择 INITIALIZE_REGISTERED_ROOT/ROOT_SUPERSEDE，class ever_committed=false/true 分别选择 INITIALIZE_REGISTERED_CLASS/CLASS_SUPERSEDE。ever_committed=true 的两类 supersede 转入 S1.5 专用 replay 事务；ever_committed=false 的两类初始化继续第 8 步，不得在此早退。
8. 对待初始化的 non-class root 或 class representative，与除此对象外的全部 ACTIVE classes 核对三类关系；任一 BLOCKED/UNKNOWN：提交 effective content、lifecycle=NONCONTRIBUTING 与 ABSTAIN_RELATION，无 token；结束。
9. 先计算并原子预留每个 principal、root、每个 touched target 的完整 \(\beta^{eff}\) 与 queue。beta=0 为 ABSTAIN_BUDGET。beta>0 后计算 \(a^-=\min\{c,a+\nu_{\mathrm{tot}}(\tau-t_a)\}\)；若 \(a^-<1\)，追加 ABSTAIN_RATE/RATE_CAP。失败释放未提交预留、lifecycle=NONCONTRIBUTING、无 token，GateState/rate state 不变；结束。两关通过才预留 acceptance key 并对 \(\mathcal V_o\) 折扣一次。
10. GateState 初值全 OFF。对 ScopeClosure 的 \(\mathcal H_o\)，前态 OFF/ON 分别取 \(\delta_{on,h}/\delta_{off,h}\)，令 \(\delta_k=\max_h\delta_{active,h,k}\)；计算 joint survival 与 proposed post-state。前置失败不改 GateState。
11. CAS 校验 joint_state、ledger、registry/equivalence/class member map、relations、budget、rate、gate、SystemMode/PendingMandatoryControl、latch、timer generation 与 queue versions；变化则释放未提交预留并重算。
12. \(s_k\ge\delta_k\) 时一次提交融合后的 \(\mathbb B_k\)、bundle/ledger/gate/rate/lifecycle=ACTIVE/ACCEPTED 与预算；对 CONJUNCTIVE、INITIALIZE_REGISTERED_ROOT、INITIALIZE_REGISTERED_CLASS，门失败提交预测态、proposed GateState、NONCONTRIBUTING/ABSTAIN_CONFLICT，并释放未提交 budget/acceptance reservations。ever-committed ROOT_SUPERSEDE、CLASS_SUPERSEDE 与 committed MERGE 不使用本条释放语义，而按 S1.5 原子烧结其专用 top-up/charge。三类首次成功均消费一个 slot并计入 \(N\)。
13. 提交后断言 ACTIVE iff exactly-one-ledger-token；失败进入 SAFE_HALT_REGISTRY_INVARIANT。
'@
$newAlgorithm = @'
2. 验证 credential chain 与 RootIdentityManifest signature；失败则 QuarantineLog+REJECT。成功即 identity-valid，以 authenticated root_type 在 outer validation 前新建/读取 Registry、冻结 TTL，并用 \(H(event\_id,processing\_token)\) 幂等收取一次不可退 processing token。retired、outer-invalid、mapping/compiler 失败事件均收费；CAS retry 不重复收费。
3. 递归解析 class/member redirect。若 representative lifecycle=RETIRED，则唯一走 RETIRED_LATE_AUDIT：只记安全审计，不写 attempt、不触发 latch、不运行 duplicate/outer/mapping/compiler；结束。
4. 对未退休对象运行 outer validator。失败追加 QUARANTINED，既有 lifecycle/ledger 不变，按冻结码决定 latch；结束。outer 不检查焦元嵌套、target-scope 集合语义或 discord。
5. 仅对 outer-valid 对象，canonical root+bundle_version+envelope_hash 全同才走 DUPLICATE_AUDIT；相对预测态不融合，只更新 last_seen/retry_count/audit；结束。
6. 非重复候选先运行 SourceAdapter mapping。certificate 缺失/过期、validity-domain 超界、drift/OOD 或其他映射失败分别记录 MAPPING_CERTIFICATE_INVALID、MAPPING_VALIDITY_DOMAIN_EXCEEDED、MAPPING_DRIFT_DETECTED 或 MAPPING_UNKNOWN；action 与 attempt_status 均为 ABSTAIN_MAPPING，不生成 typed claim；结束。
7. mapping VALID 后推进 highest_outer_valid_attempt_version，再按 class_record 对全 class 运行 \(J_{merge}\)，非 class 运行 \(J_o\) 与 ScopeClosure。compiler cap/semantic failure 只写 attempt，不推进 effective version；committed lifecycle/token 保持。合法 joint 继续。
8. 用 candidate、全部 ACTIVE roots、当前 context、三套生成图和高阶超边执行冻结证书生成器：祖先闭包→收缩已建模潜变量→检查 identity/derivation 重叠、未建模共同祖先、过期边、未裁决超边与 completeness。返回最小见证子图；BLOCKED/UNKNOWN 强制 ABSTAIN_RELATION。add/retire/merge/supersede 后旧证书失效，必须重建。
9. 硬检 class/root expires_at 并选择 INITIALIZE_REGISTERED_ROOT、ROOT_SUPERSEDE、INITIALIZE_REGISTERED_CLASS 或 CLASS_SUPERSEDE。ever-committed supersede 转入 S1.5 专用 replay；never-committed 初始化继续预算。
10. 仅对集合 ELIGIBLE 的候选，原子预留 principal/root/每个 target 的完整 \(\beta^{eff}\) 与 queue；beta=0 为 ABSTAIN_BUDGET。随后计算并预留 acceptance slot；不足为 ABSTAIN_RATE。失败释放未提交预留，GateState 不变。
11. 对 \(q_o=D_{\beta^{eff}}(\mathcal V_o)\) 计算 \(\widetilde b=\mathbb B_{k^-}\odot q_o\)、\(s_k=1-\widetilde b(\varnothing)\) 和 proposed GateState。仅 \(s_k\ge\delta_k\) 时允许 \(\mathcal N(\widetilde b)\)。
12. CAS 校验 joint_state、ledger、registry/equivalence/class member map、certificate/graphs、budget、rate、gate、SystemMode/PendingMandatoryControl、latch、timer generation 与 queue versions；变化则释放未提交预留并从第 6 步重算。
13. 门通过时一次提交 belief、bundle/ledger/gate/rate/lifecycle=ACTIVE/ACCEPTED 与预算；门失败提交预测态、proposed GateState、NONCONTRIBUTING/ABSTAIN_CONFLICT，并按路由释放未提交 reservations。ever-committed supersede/merge 服从 S1.5 专用不可退规则。
14. 提交后断言 ACTIVE iff exactly-one-ledger-token；失败进入 SAFE_HALT_REGISTRY_INVARIANT。
'@
$oldAlgorithm = $oldAlgorithm.Replace("`r`n", "`n")
$newAlgorithm = $newAlgorithm.Replace("`r`n", "`n")
$s1 = Replace-Exact $s1 $oldAlgorithm $newAlgorithm 's1-algorithm'

$s1 = $s1.Replace('relations、全额 budget、rate 与 gate', 'fresh SetwiseEligibilityCertificate、全额 budget、rate 与 gate')
$s1 = $s1.Replace('历史 relation/gate 通过则 ACTIVE', '以替换后的 ACTIVE 集合重建 fresh SetwiseEligibilityCertificate；证书和历史 gate 通过则 ACTIVE')
$s1 = $s1.Replace('后续 relation/gate 失败或 beta=0', '后续 fresh SetwiseEligibilityCertificate/gate 失败或 beta=0')
$s1 = $s1.Replace('使用当前 \(\tau\)、class policy、relations、全额 budget、rate 与 gate', '使用当前 \(\tau\)、class policy、fresh SetwiseEligibilityCertificate、全额 budget、rate 与 gate')
$s1 = $s1.Replace('全通过才替换 map、current target map 与 top-up，并从 class first_effective_event 重放。', '全通过后先替换候选 map并重建覆盖新 ACTIVE 集合的 SetwiseEligibilityCertificate；证书 ELIGIBLE 才替换 current target map 与 top-up并从 class first_effective_event 重放，否则保留旧 map/token/lifecycle。')

$s1 = Replace-Exact $s1 @'
每个 source adapter 必须机械验证：certificate 绑定 training/calibration dataset、validity domain、missing/lateness/OOD policy、schema/code hash；证书缺失、过期、漂移或超域时唯一输出 MAPPING_UNKNOWN/ABSTAIN_MAPPING，不得生成可合取 claim。共享 \(u\) 作为 within-root coupling 假设显式入 manifest；替代 coupling 的敏感性测试不得复用 confirm test 调参。
'@ @'
每个 source adapter 必须机械验证：certificate 绑定 training/calibration dataset、validity domain、missing/lateness/OOD policy、schema/code hash。证书缺失/过期、超域、漂移/OOD 与其他未知映射分别输出 MAPPING_CERTIFICATE_INVALID、MAPPING_VALIDITY_DOMAIN_EXCEEDED、MAPPING_DRIFT_DETECTED、MAPPING_UNKNOWN；四者的强制 action/attempt_status 均为 ABSTAIN_MAPPING，不得生成可合取 claim。共享 \(u\) 只是具名 coupling 敏感性模型；主分析使用联合校准 root-level mapper 或冻结 coupling family 包络。
'@ 's1-mapping-codes'

$s1 = $s1.Replace('NormativeReleaseManifest 至少绑定 main-v20/S1-v20/S2-v20/v6.5', 'NormativeReleaseManifest 至少绑定 main-v20.1/S1-v20.1/S2-v20.1/v6.7')
$s1 = $s1.Replace('### S1.17.1 Root/View Invariance', '### S1.17.1 实现不变量：Root/View Invariance')
$s1 = $s1.Replace('### S1.17.2 Replay/Canonicalization Equivalence', '### S1.17.2 实现不变量：Replay/Canonicalization Equivalence')
$s1 = $s1.Replace('### S1.17.3 Setwise Eligibility Relative Soundness', '### S1.17.3 实现不变量：Setwise Eligibility Relative Soundness')
[System.IO.File]::WriteAllText($s1Path, $s1, $utf8)

# S2
$s2Path = Join-Path $Workspace '补充材料S2-v20.1-运行合同与观察映射规范.md'
$s2 = [System.IO.File]::ReadAllText($s2Path, [System.Text.Encoding]::UTF8)
$s2 = Replace-Exact $s2 '# 补充材料 S2（v20）：运行合同、观察映射与集合资格规范' '# 补充材料 S2（v20.1）：运行合同、观察映射与集合资格规范' 's2-title'
$s2 = Replace-Exact $s2 @'
> 本材料展开主文 v20 的字段、异常分支与编译 schema。主文、S1、S2 与实验 v6.5 由同一 NormativeReleaseManifest 绑定，互不覆盖；任一冲突或 hash 不一致都使整个 release 无效。实现与 P0 性质测试对拍该唯一版本包。
'@ @'
> 本材料展开主文 v20.1 的字段、异常分支与编译 schema。主文、S1、S2 与实验 v6.7 由同一 NormativeReleaseManifest 绑定，互不覆盖；任一冲突或 hash 不一致都使整个 release 无效。实现与 P0 性质测试对拍该唯一版本包。
'@ 's2-binding'

$s2 = Replace-Exact $s2 @'
`NormativeReleaseManifest` 至少包含：`release_id`、`main_version/hash`、`S1_version/hash`、`S2_version/hash`、`experiment_version/hash`、`SafetyArtifactIR_schema_version/hash`、`compiler_version/hash`、`failure_code_registry_hash`、`OperationalSafetyArtifact_hash`、`analysis_container_hash` 与有向依赖边。package validator 必须验证全部文件存在、hash 匹配、引用版本闭合、schema 兼容和无循环覆盖。不存在正文优先、S2 优先或“更保守者优先”；语义冲突唯一返回 `PACKAGE_CONSISTENCY_INVALID` 并阻止预注册/test 解封。
'@ @'
`NormativeReleaseManifest` 至少包含：`release_id`、`main_version/hash`、`S1_version/hash`、`S2_version/hash`、`experiment_version/hash`、`SafetyArtifactIR_schema_version/hash`、`compiler_version/hash`、`failure_code_registry_hash`、`OperationalSafetyArtifact_hash`、`analysis_container_hash` 与有向依赖边。package validator 必须验证全部文件存在、hash 匹配、引用版本闭合、schema 兼容和无循环覆盖。不存在正文优先、S2 优先或“更保守者优先”；语义冲突唯一返回 `PACKAGE_CONSISTENCY_INVALID` 并阻止预注册/test 解封。

ClaimRegister 必须包含 C-Audit、C-Conserve、C-System、C-HB 与 C-Budget，并把每个 ID 绑定到 S1 oracle、v6.7 estimand、否证规则和允许降级措辞。RootRegistry 的 attempt 记录按 `(bundle_version,event_id)` 追加，字段为 `reason_code → action → attempt_status`；同一版本的后续事件不得覆盖既往记录。
'@ 's2-claim-attempt'

$s2 = $s2.Replace('单次运行共享潜变量 \(J_{merge}\)', '单次运行冻结的 root/class-level mapper \(J_{merge}\)；共享潜变量交集只作为具名敏感性模型')

$s2 = Replace-Exact $s2 @'
事务顺序固定为：预测；最小身份认证并冻结 TTL；解析 retired/class redirect；RETIRED_LATE_AUDIT 或 outer identity/seal 验证；去重；按对象类型单次运行 \(J_o\) 或全类 \(J_{merge}\)；选路由；提交 processing token；预留主体/root/每个 target 的完整 beta 与 queue；计算 \(a^-\) 并预留 acceptance slot；只折扣一次 root-global valuation；计算 joint gate/GateState。对 CONJUNCTIVE、INITIALIZE_REGISTERED_ROOT 与 INITIALIZE_REGISTERED_CLASS，早退提交预测态，门失败提交预测态和 proposed GateState、释放未提交 budget/acceptance reservations；成功原子提交 belief、bundle、ledger、registry/budget/gate/rate。对 ever-committed supersede/merge，预算和 top-up 的提交/保留严格服从前述生命周期专用规则，不得套用首次 admission 的释放语义；committed MERGE canonicalization 失败必须 fail-stop。mandatory replay 不能完成时只提交 SAFE_HALT 状态，不提交半成品 belief。
'@ @'
事务顺序固定为：预测；最小身份认证、冻结 TTL 并以 event_id 幂等提交一次 processing token；解析 retired/class redirect；RETIRED_LATE_AUDIT 或 outer identity/seal 验证；outer-valid 后精确去重；SourceAdapter mapping；按对象类型运行 root/class-level mapper \(J_o/J_{merge}\) 与 ScopeClosure；用当前 candidate、ACTIVE roots 和 context 重建 SetwiseEligibilityCertificate；仅 ELIGIBLE 才选 admission/supersede 路由并预留主体/root/每个 target 的完整 beta、queue 和 acceptance slot；只折扣一次 root-global valuation；计算 joint gate/GateState。retired、outer-invalid、mapping/compiler 失败事件均收一次 processing token，CAS retry 不重复。对首次 admission，早退提交预测态并释放未提交 reservations；对 ever-committed supersede/merge，预算和 top-up 服从生命周期专用不可退规则。committed MERGE canonicalization 失败必须 fail-stop；mandatory replay 不能完成时只提交 SAFE_HALT，不提交半成品 belief。
'@ 's2-transaction-order'

$s2 = Replace-Exact $s2 @'
`validity_status != VALID`、certificate 缺失/过期、schema mismatch、OOD/drift 或 mapping hash 不一致时，唯一返回 `MAPPING_UNKNOWN` / `ABSTAIN_MAPPING`。outer signature valid 不得把 mapping semantic failure 晋级为有效 claim。共享潜变量 coupling 是版本化假设，改变 coupling 必须开启新 epoch 并改变 release hash。
'@ @'
mapping reason_code 唯一化如下：certificate 缺失/过期或 schema/hash mismatch → `MAPPING_CERTIFICATE_INVALID`；超出适用域 → `MAPPING_VALIDITY_DOMAIN_EXCEEDED`；OOD/drift → `MAPPING_DRIFT_DETECTED`；其余无法裁决 → `MAPPING_UNKNOWN`。四者均强制 action=`ABSTAIN_MAPPING`、attempt_status=`ABSTAIN_MAPPING`，不得生成 typed claim。within-root coupling 是版本化假设；主分析使用联合校准 root-level mapper 或冻结 coupling-family 包络，SAFE/排序翻转返回 `COUPLING_SENSITIVE` 并开启新 epoch 才能解除。
'@ 's2-mapping-codes'

$s2 = Replace-Exact $s2 @'
二元 PCR/OLR 关系只是必要输入。存在未裁决高阶超边、未建模共享祖先、过期 relation、context mismatch 或根集合变化时，decision 必须 UNKNOWN/BLOCKED；不得由 pairwise ELIGIBLE 聚合得到集合 ELIGIBLE。ACTIVE 集合在 add/retire/merge/supersede 后必须重签证书。
'@ @'
二元 PCR/OLR 关系只是必要输入。证书生成器构造 derivation、observation-generation 与 physical-latent 图的祖先闭包，收缩已由 joint factor 显式建模且具校准证据的潜变量；identity/derivation 重叠、未建模共同祖先、过期边、context mismatch、未裁决高阶超边或 completeness 缺口均返回 BLOCKED/UNKNOWN 及最小见证子图。仅在预注册 random-set 生成语义下满足 distinctness 充分条件时返回 ELIGIBLE。复杂度为 \(O(|V|+|E|+|H|)\)，超 cap 为 ABSTAIN_COMPLEXITY。ACTIVE 集合在 add/retire/merge/supersede 后旧证书立即失效并必须重签。
'@ 's2-setwise-generator'

$s2 = $s2.Replace('- `UTILITY_SENSITIVE`', '- `COUPLING_SENSITIVE`' + "`r`n" + '- `UTILITY_SENSITIVE`')
$s2 = Replace-Exact $s2 @'
路由合同唯一化如下：MAPPING_UNKNOWN 是 reason_code，ABSTAIN_MAPPING 是其强制 action，attempt_status=ABSTAIN_MAPPING；该 action 不生成 typed claim、不进入集合资格或融合，never-committed 条目置 NONCONTRIBUTING，committed lifecycle/token 保持，按严重度 LATCH_SET。全部 SETWISE_* 是集合资格 reason_code，强制 action=ABSTAIN_RELATION、attempt_status=ABSTAIN_RELATION；相对预测态不作 fusion，不改变 ActiveLedger、budget、rate 或 GateState，never-committed 条目置 NONCONTRIBUTING，committed lifecycle/token 保持，按方向/严重度 LATCH_SET。UTILITY_SENSITIVE 是 reason_code，强制 action 为 PROBE/INDEPENDENT_REVIEW，并设置 safe_eligible=false；只有新 epoch 下独立签署的效用族或复核决定才能解除，不得仅记录日志后继续 SAFE。
'@ @'
路由合同唯一化如下：四个 MAPPING_* reason_code 均强制 action=ABSTAIN_MAPPING、attempt_status=ABSTAIN_MAPPING；该 action 不生成 typed claim、不进入集合资格或融合。全部 SETWISE_* 强制 action=ABSTAIN_RELATION、attempt_status=ABSTAIN_RELATION。COUPLING_SENSITIVE 与 UTILITY_SENSITIVE 均强制 action=PROBE/INDEPENDENT_REVIEW、safe_eligible=false；只有新 epoch 下独立签署的 mapper/coupling family 或效用族才能解除。never-committed 条目置 NONCONTRIBUTING，committed lifecycle/token 保持；各路由均按预签严重度 LATCH_SET。
'@ 's2-route-contract'

[System.IO.File]::WriteAllText($s2Path, $s2, $utf8)
Write-Output "Revised S1 and S2"
