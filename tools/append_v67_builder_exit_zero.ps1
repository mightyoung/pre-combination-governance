$path = Join-Path $PSScriptRoot 'build_v67_workbook.mjs'
$text = [System.IO.File]::ReadAllText($path, [System.Text.Encoding]::UTF8)
if (-not $text.Contains('process.exitCode = 0;')) {
  $text = $text.TrimEnd() + [Environment]::NewLine + 'process.exitCode = 0;' + [Environment]::NewLine
  [System.IO.File]::WriteAllText($path, $text, [System.Text.UTF8Encoding]::new($false))
}
