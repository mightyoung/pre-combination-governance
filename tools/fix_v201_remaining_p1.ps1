$ErrorActionPreference = 'Stop'

function Read-Utf8([string]$Path) {
    [System.IO.File]::ReadAllText((Resolve-Path -LiteralPath $Path), [System.Text.Encoding]::UTF8).Replace("`r`n", "`n")
}

function Write-Utf8([string]$Path, [string]$Text) {
    [System.IO.File]::WriteAllText((Resolve-Path -LiteralPath $Path), $Text, [System.Text.UTF8Encoding]::new($false))
}

function Replace-One([string]$Text, [string]$Old, [string]$New, [string]$Label) {
    $count = ([regex]::Matches($Text, [regex]::Escape($Old))).Count
    if ($count -ne 1) { throw "[$Label] expected one match, found $count" }
    $Text.Replace($Old, $New)
}

$files = @(
    '00-论文-中文阅读稿v20.1-一致性修复与投稿主线收敛版.md',
    '补充材料S1-v20.1-组合前治理证明与性质测试.md',
    '补充材料S2-v20.1-运行合同与观察映射规范.md'
)

foreach ($path in $files) {
    $text = Read-Utf8 $path
    $text = $text.Replace('RootRegistry attempt_status=NO_ATTEMPT', 'audit_display=NO_ATTEMPT（RootRegistry attempt 不存在；NO_ATTEMPT 不属于 attempt_status enum）')
    $text = $text.Replace('attempt_status=NO_ATTEMPT', 'audit_display=NO_ATTEMPT（RootRegistry attempt 不存在；NO_ATTEMPT 不属于 attempt_status enum）')
    Write-Utf8 $path $text
}

$path = '实验设计与执行计划v6.7-精简确认性预注册蓝图.md'
$text = Read-Utf8 $path
$old = '以 bundle 为 bootstrap/方差单位，按层加权并保持 A/G* 配对。主分析使用 stratified paired bootstrap 或预签等价 score estimator；若 pilot 表明 batch ICC 非忽略，则使用 cluster-respecting bootstrap/estimating equation。variant、attack 和 algorithm seed 先按冻结 reducer 汇总到 bundle，禁止当独立样本。'
$new = '以 bundle 为 bootstrap/方差单位，按层加权并保持 A/G* 配对。唯一主估计为按目标层权的 paired stratified bootstrap（20,000 次，SeedManifest 固定）；仅当 pilot 触发预签 batch-ICC 阈值时，按 SAP 切换为 cluster-respecting paired bootstrap。score estimator/estimating equation 只作 sensitivity，不得替代主估计或恢复失败主张。variant、attack 和 algorithm seed 先按冻结 reducer 汇总到 bundle，禁止当独立样本。'
$text = Replace-One $text $old $new 'unique primary estimator'
$old = 'claim 间固定序列 Q→C-System→C-HB→C-Conserve-Benefit→C-Budget。'
$new = 'claim/资格门固定序列 Q→C-System→C-HB→C-Conserve-Benefit→C-Budget→表示一致性 Gate 5；Gate 5 只判定表示资格，不恢复任何已失败的标题级经验主张。'
$text = Replace-One $text $old $new 'Gate 5 sequence'
Write-Utf8 $path $text

Write-Output 'remaining three P1 items fixed'
