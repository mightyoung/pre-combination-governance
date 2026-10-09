$path = Join-Path $PSScriptRoot 'build_v67_workbook.mjs'
$text = [System.IO.File]::ReadAllText($path, [System.Text.Encoding]::UTF8)

$text = $text.Replace(
  's.getRange("B29").formulas = [["=((NORM.S.INV(1-B4)+NORM.S.INV(B5))^2*B7/(B6^2))*B8/(1-B9)*B11"]];',
  's.getRange("B29").formulas = [["=((NORM.S.INV(1-B4)+NORM.S.INV(B5))^2*B7/(B6^2))*B8/(1-B9)*B12"]];'
)
$text = $text.Replace(
  's.getRange("B30").formulas = [["=MAX(ROUNDUP(B29/B10,0)*B10,B10*B12)"]];',
  's.getRange("B30").formulas = [["=MAX(ROUNDUP(B29/B10,0)*B10,B10*B11)"]];'
)
$text = $text.Replace('Inputs!B11/Inputs!B10', 'Inputs!B12/Inputs!B10')
$text = $text.Replace(
  's.getRange("D18:D19").formulas = [["=Inputs!B14"],["=Inputs!B14"]];',
  's.getRange("D18:D19").formulas = [["=Inputs!B13"],["=Inputs!B13"]];'
)

$text = $text.Replace(
  '["一致性检查", null, "PASS/FAIL", null, null, "人日、CPU/GPU、存储、周数"],',
  '["算术勾稽", null, "PASS/FAIL", null, null, "人日、CPU/GPU、存储与周数是否跨表一致"],'
)
$text = $text.Replace(
  'B17:''=IF(AND(B14=Personnel!E14,B7<=Inputs!B22,B8<=Inputs!B23,B13<=Inputs!B21*0.75,MAX(Schedule!C4:C13)=Inputs!B24),"PASS","FAIL")'',',
  'B17:''=IF(AND(B14=Personnel!E14,B7=Schedule!F15,B8=Schedule!G15,MAX(Schedule!C4:C13)=Inputs!B24,Schedule!B16=Inputs!B24+1,Schedule!C16=Inputs!B24+Inputs!B25),"PASS","FAIL")'','
)
$text = $text.Replace(
  'for (const [cell, f] of Object.entries(formulas)) s.getRange(cell).formulas=[[f]];',
  'for (const [cell, f] of Object.entries(formulas)) s.getRange(cell).formulas=[[f]];`n  s.getRange("A18:F18").values = [["资源容量门", null, "PASS/FAIL", null, null, "CPU/GPU 与高包络存储均须留足资源"]];`n  s.getRange("B18").formulas = [[''=IF(AND(B7<=Inputs!B22,B8<=Inputs!B23,B13<=Inputs!B21*0.75),"PASS","FAIL")'']];'
)
$text = $text.Replace(
  's.getRange("B4:B17").format.fill = C.paleBlue;',
  's.getRange("B4:B18").format.fill = C.paleBlue;'
)
$text = $text.Replace(
  's.getRange("B17").format.fill = C.green;',
  's.getRange("B17").format.fill = C.green;`n  s.getRange("B18").format.fill = C.red;'
)

$text = $text.Replace(
  '["B11","Information Fusion cover letter 六问与 50 refs 上限","OPEN","submission audit","PI","G9","不投稿"],',
  '["B11","Information Fusion cover letter 六问与 50 refs 上限","OPEN","submission audit","PI","G9","不投稿"],`n    ["B12","4 TB 名义存储在 25% 余量下不足以覆盖 v6.7 高包络","OPEN","新增可用容量或密封压缩/复制方案","软件/PI","G5","资源门 FAIL；禁止解封 test"],'
)
$text = $text.Replace('s.getRange("A4:G14").values=rows;', 's.getRange("A4:G15").values=rows;')
$text = $text.Replace('grid(s, "A3:G14");', 'grid(s, "A3:G15");')
$text = $text.Replace('s.getRange("C4:C14").format.fill=C.red;', 's.getRange("C4:C15").format.fill=C.red;')
$text = $text.Replace('s.getRange("C4:C14").dataValidation', 's.getRange("C4:C15").dataValidation')

[System.IO.File]::WriteAllText($path, $text, [System.Text.UTF8Encoding]::new($false))
