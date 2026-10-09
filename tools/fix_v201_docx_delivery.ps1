$path = Join-Path $PSScriptRoot 'build_v201_docx_delivery.py'
$text = [System.IO.File]::ReadAllText($path, [System.Text.Encoding]::UTF8)
$text = $text.Replace('citation["reference_sequence_ok"]', 'citation["sequence_ok"]')
[System.IO.File]::WriteAllText($path, $text, [System.Text.UTF8Encoding]::new($false))
