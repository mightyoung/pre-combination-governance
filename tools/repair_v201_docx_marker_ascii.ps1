$path = Join-Path $PSScriptRoot 'build_v201_docx_delivery.py'
$lines = [System.IO.File]::ReadAllLines($path, [System.Text.Encoding]::UTF8)
$inside = $false
$out = [System.Collections.Generic.List[string]]::new()
foreach ($line in $lines) {
  if ($line.StartsWith('def insert_main_figure(')) { $inside = $true }
  if ($inside -and $line.TrimStart().StartsWith('marker = ')) {
    $out.Add('    marker = "\u56fe1\uff1a\u5b89\u5168\u5de5\u4ef6\u5230\u5728\u7ebf\u6eaf\u6e90\u7ea6\u675f\u878d\u5408\u95ed\u73af"')
    continue
  }
  if ($inside -and $line.StartsWith('def structural_check(')) { $inside = $false }
  $out.Add($line)
}
[System.IO.File]::WriteAllLines($path, $out, [System.Text.UTF8Encoding]::new($false))
