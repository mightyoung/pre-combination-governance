$path = Join-Path $PSScriptRoot 'build_v67_workbook.mjs'
$lines = [System.IO.File]::ReadAllLines($path, [System.Text.Encoding]::UTF8)
$out = [System.Collections.Generic.List[string]]::new()
$inResource = $false
$inBlockers = $false

foreach ($line in $lines) {
  if ($line -eq '// ResourceSummary') { $inResource = $true; $inBlockers = $false }
  if ($line -eq '// Schedule') { $inResource = $false }
  if ($line -eq '// Blockers') { $inBlockers = $true }
  if ($line -eq '// Sources') { $inBlockers = $false }

  if ($inResource -and $line.Contains('for (const [cell, f] of Object.entries(formulas))')) {
    $out.Add('  for (const [cell, f] of Object.entries(formulas)) s.getRange(cell).formulas=[[f]];')
    $out.Add('  s.getRange("A18:F18").values = [["\u8d44\u6e90\u5bb9\u91cf\u95e8", null, "PASS/FAIL", null, null, "CPU/GPU \u4e0e\u9ad8\u5305\u7edc\u5b58\u50a8\u5747\u987b\u7559\u8db3\u8d44\u6e90"]];')
    $out.Add('  s.getRange("B18").formulas = [[''=IF(AND(B7<=Inputs!B22,B8<=Inputs!B23,B13<=Inputs!B21*0.75),"PASS","FAIL")'']];')
    continue
  }

  if ($inResource -and $line.Contains('s.getRange("B17").format.fill')) {
    $out.Add('  s.getRange("B17").format.fill = C.green;')
    $out.Add('  s.getRange("B18").format.fill = C.red;')
    continue
  }

  if ($inResource -and $line.TrimStart().StartsWith('["') -and $line.Contains('"PASS/FAIL"')) {
    $out.Add('    ["\u7b97\u672f\u52fe\u7a3d", null, "PASS/FAIL", null, null, "\u4eba\u65e5\u3001CPU/GPU\u3001\u5b58\u50a8\u4e0e\u5468\u6570\u662f\u5426\u8de8\u8868\u4e00\u81f4"],')
    continue
  }

  if ($inBlockers -and $line.Contains('["B11"')) {
    $out.Add($line)
    $out.Add('    ["B12","4 TB \u540d\u4e49\u5b58\u50a8\u5728 25% \u4f59\u91cf\u4e0b\u4e0d\u8db3\u4ee5\u8986\u76d6 v6.7 \u9ad8\u5305\u7edc","OPEN","\u65b0\u589e\u53ef\u7528\u5bb9\u91cf\u6216\u5bc6\u5c01\u538b\u7f29/\u590d\u5236\u65b9\u6848","\u8f6f\u4ef6/PI","G5","\u8d44\u6e90\u95e8 FAIL\uff1b\u7981\u6b62\u89e3\u5c01 test"],')
    continue
  }

  $out.Add($line)
}

[System.IO.File]::WriteAllLines($path, $out, [System.Text.UTF8Encoding]::new($false))
