$ErrorActionPreference = 'Stop'
$tickN = [string][char]0x60 + 'n'
$s2 = Get-ChildItem -LiteralPath (Split-Path $PSScriptRoot -Parent) -File | Where-Object { $_.Name -like '*S2-v20.1*.md' } | Select-Object -First 1
$exp = Get-ChildItem -LiteralPath (Split-Path $PSScriptRoot -Parent) -File | Where-Object { $_.Name -like '*v6.7*.md' } | Select-Object -First 1
if (-not $s2 -or -not $exp) { throw 'target markdown file not found' }
$utf8 = [System.Text.Encoding]::UTF8
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$text = [System.IO.File]::ReadAllText($s2.FullName, $utf8)
$text = $text.Replace('NO_ATTEMPT' + $tickN + '- `ROOT_TYPE', 'NO_ATTEMPT' + "`n" + '- `ROOT_TYPE')
$text = $text.Replace('QUARANTINED' + $tickN + '- `MAPPING', 'QUARANTINED' + "`n" + '- `MAPPING')
[System.IO.File]::WriteAllText($s2.FullName, $text, $utf8NoBom)
$text = [System.IO.File]::ReadAllText($exp.FullName, $utf8)
$text = $text.Replace($tickN + '- C-Conserve-Benefit', "`n" + '- C-Conserve-Benefit')
[System.IO.File]::WriteAllText($exp.FullName, $text, $utf8NoBom)
Write-Output 'generated newline markers repaired'
