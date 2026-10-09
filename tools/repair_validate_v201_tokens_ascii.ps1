$path = Join-Path $PSScriptRoot 'validate_v201_package.py'
$lines = [System.IO.File]::ReadAllLines($path, [System.Text.Encoding]::UTF8)
$out = [System.Collections.Generic.List[string]]::new()
$insideStages = $false
foreach ($line in $lines) {
  if ($line.Contains('stage_tokens = [')) { $insideStages = $true }
  if ($insideStages -and $line.Contains('predictor",')) {
    $out.Add('        "predictor",')
    continue
  }
  if ($insideStages -and $line.Trim() -eq ']') { $insideStages = $false }
  $out.Add($line)
}
[System.IO.File]::WriteAllLines($path, $out, [System.Text.UTF8Encoding]::new($false))
