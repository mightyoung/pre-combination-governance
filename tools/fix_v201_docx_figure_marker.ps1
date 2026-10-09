$path = Join-Path $PSScriptRoot 'build_v201_docx_delivery.py'
$text = [System.IO.File]::ReadAllText($path, [System.Text.Encoding]::UTF8)
$text = $text.Replace('marker = "![图1：安全工件到在线溯源约束融合闭环]"', 'marker = "图1：安全工件到在线溯源约束融合闭环"')
$text = $text.Replace('if p.text.strip().startswith(marker)', 'if marker in p.text')
[System.IO.File]::WriteAllText($path, $text, [System.Text.UTF8Encoding]::new($false))
