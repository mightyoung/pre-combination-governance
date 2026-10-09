$ErrorActionPreference = 'Stop'
$path = Join-Path $PSScriptRoot 'fix_v201_consistency.ps1'
$text = [System.IO.File]::ReadAllText($path, [System.Text.Encoding]::UTF8)
$fullWidthColon = [char]0xFF1A
$old = '$routePattern = ''(?ms)^1\. \*\*REJECT_SCHEMA\*\*:.*?^8\. \*\*CONJUNCTIVE\*\*:.*?$'''
$new = '$routePattern = ''(?ms)^1\. \*\*REJECT_SCHEMA\*\*' + $fullWidthColon + '.*?^8\. \*\*CONJUNCTIVE\*\*' + $fullWidthColon + '.*?$'''
if (-not $text.Contains($old)) { throw 'route pattern line not found' }
$text = $text.Replace($old, $new)
[System.IO.File]::WriteAllText($path, $text, [System.Text.UTF8Encoding]::new($true))
Write-Output 'helper script route regex repaired'
