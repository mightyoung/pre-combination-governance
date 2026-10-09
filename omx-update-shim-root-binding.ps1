$ErrorActionPreference = 'Stop'
$target = 'C:\Users\might\.codex\hooks\omx-native-hook-windows-shim.ps1'
$backup = 'C:\Users\might\.codex\hooks\omx-native-hook-windows-shim.ps1.before-root-binding-20260720.ps1'
$encoding = [System.Text.UTF8Encoding]::new($false)
$lines = [System.IO.File]::ReadAllLines($target, $encoding)
if ($lines -contains '    $startInfo.WorkingDirectory = [string]$resolvedCwd') {
    Write-Output 'already-installed'
    exit 0
}
$next = [System.Collections.Generic.List[string]]::new()
$foundSessionId = $false
$foundStateId = $false
$foundArguments = $false
foreach ($line in $lines) {
    if ($line.Trim() -eq '$sessionId = [string]$payload.session_id') {
        [void]$next.Add('$sessionId = ([string]$payload.session_id).Trim()')
        $foundSessionId = $true
        continue
    }
    if ($line.Trim() -eq '$sessionId = [string]$payload.sessionId') {
        [void]$next.Add('$sessionId = ([string]$payload.sessionId).Trim()')
        continue
    }
    if ($line -eq '                    if ([string]$state.session_id -eq $sessionId -and -not [string]::IsNullOrWhiteSpace([string]$state.cwd)) {') {
        [void]$next.Add('                    if (([string]$state.session_id).Trim() -eq $sessionId -and -not [string]::IsNullOrWhiteSpace([string]$state.cwd)) {')
        $foundStateId = $true
        continue
    }
    [void]$next.Add($line)
    if ($line.StartsWith('$startInfo.Arguments = ')) {
        [void]$next.Add('if (-not [string]::IsNullOrWhiteSpace([string]$resolvedCwd)) {')
        [void]$next.Add('    $startInfo.WorkingDirectory = [string]$resolvedCwd')
        [void]$next.Add('    $startInfo.Environment[''OMX_ROOT''] = [string]$resolvedCwd')
        [void]$next.Add('}')
        $foundArguments = $true
    }
}
if (-not ($foundSessionId -and $foundStateId -and $foundArguments)) {
    throw "Expected shim markers missing: session=$foundSessionId state=$foundStateId arguments=$foundArguments"
}
[System.IO.File]::Copy($target, $backup, $true)
[System.IO.File]::WriteAllLines($target, $next.ToArray(), $encoding)
Write-Output $target
Write-Output $backup
