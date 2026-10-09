# 远端只读盘点脚本（2026-07-23）
# 用途：按 AGENTS.md 要求，在任何远端写入/实验动作之前重新采集磁盘、GPU、进程与数据集状态。
# 边界：只读。本脚本不下载数据、不解压、不启动任何实验（SHK-001B 与确认性实验按 GateChecklist 处于 BLOCKED）。
# 凭据：密码由 ssh 交互式提示输入——不要把密码写进 .env、脚本、命令行或历史（AGENTS.md 凭据规则）。
# 运行：在 PowerShell 中 .\远端只读盘点-20260723.ps1（需要 Windows 自带 OpenSSH：ssh、ssh-keyscan、ssh-keygen）

$ErrorActionPreference = "Stop"
$RemoteHost = "192.168.11.16"
$Port       = 10022
$User       = "r4900g3"
# AGENTS.md 已核验指纹（ssh-ed25519）：
$ExpectedFp = "eDfwLjrpTces2mQp4d+gKdg2i/4t7k7sLfF/nLtx1oA"

Write-Host "[1/3] 采集主机密钥并核对指纹..."
$scan = & ssh-keyscan -p $Port -t ed25519 $RemoteHost 2>$null
if (-not $scan) { throw "ssh-keyscan 失败：无法取得 $RemoteHost 的 ed25519 主机密钥（检查网络/端口）" }
$tmpKnown = Join-Path $env:TEMP ("rfb-known-hosts-" + [guid]::NewGuid().ToString("N"))
$scan | Out-File -Encoding ascii -FilePath $tmpKnown
try {
    $fpLine = & ssh-keygen -lf $tmpKnown
    $fp = ($fpLine -split "\s+")[1]  # 形如 SHA256:xxxx
    if (($fp -ne "SHA256:$ExpectedFp") -and ($fp -ne $ExpectedFp)) {
        throw "主机密钥指纹不匹配！观测=$fp 期望=SHA256:$ExpectedFp —— 立即停止，不要输入密码，按 AGENTS.md 重新核对主机身份。"
    }
    Write-Host "指纹匹配：$fp"

    Write-Host "[2/3] 登录并执行只读盘点（将提示输入密码）..."
    $inventory = @(
        "echo '== host/time =='; hostname; date -u",
        "echo '== disk =='; df -h /home; df -h /home/r4900g3/yhh 2>/dev/null || true",
        "echo '== memory =='; free -h",
        "echo '== gpu =='; nvidia-smi 2>/dev/null || echo 'nvidia-smi unavailable'",
        "echo '== workdir =='; ls -la /home/r4900g3/yhh/ 2>/dev/null || true",
        "echo '== datasets =='; ls -la /home/r4900g3/yhh/datasets/ 2>/dev/null || true",
        "echo '== dataset sizes =='; du -sh /home/r4900g3/yhh/datasets/* 2>/dev/null | sort -h || true",
        "echo '== top processes =='; ps -eo pid,user,%cpu,%mem,etime,cmd --sort=-%cpu | head -20"
    ) -join "; "

    $logName = "remote-inventory-{0:yyyyMMdd-HHmmss}.log" -f (Get-Date)
    & ssh -p $Port -o UserKnownHostsFile="$tmpKnown" -o StrictHostKeyChecking=yes "$User@$RemoteHost" $inventory |
        Tee-Object -FilePath (Join-Path $PSScriptRoot $logName)

    Write-Host "[3/3] 完成。盘点日志：$logName"
    Write-Host "提醒：这只是只读盘点。任何实验（含 C2 sizing smoke）须先完成改进计划批次 D（回归绿灯+重封基线），且 GateChecklist 相应门槛不为 BLOCKED。"
}
finally {
    Remove-Item -Force $tmpKnown -ErrorAction SilentlyContinue
}
