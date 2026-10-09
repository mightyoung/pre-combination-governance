$path = Join-Path $PSScriptRoot 'build_v67_workbook.mjs'
$text = [System.IO.File]::ReadAllText($path, [System.Text.Encoding]::UTF8)
$text = $text.Replace('s.getRange("A3:E26").values = [', 's.getRange("A3:E25").values = [')
$text = $text.Replace('s.getRange("A3:F18").values = [', 's.getRange("A3:F17").values = [')
[System.IO.File]::WriteAllText($path, $text, [System.Text.UTF8Encoding]::new($false))
