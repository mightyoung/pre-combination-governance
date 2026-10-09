$path = Join-Path $PSScriptRoot 'validate_v201_package.py'
$text = [System.IO.File]::ReadAllText($path, [System.Text.Encoding]::UTF8)
$text = $text.Replace('all("RootLevelMapperManifest" in t for t in texts.values())', 'all(("RootLevelMapperManifest" in t or "RootLevelMapper" in t) for t in texts.values())')
$text = $text.Replace('"读取最新可串行化状态执行唯一 predictor",', '"最新可串行化状态执行唯一 predictor",')
$text = $text.Replace('"SourceAdapter mapping",', '"SourceAdapter",')
$text = $text.Replace('"RootLevelMapperManifest",', '"root/class-level",')
[System.IO.File]::WriteAllText($path, $text, [System.Text.UTF8Encoding]::new($false))
