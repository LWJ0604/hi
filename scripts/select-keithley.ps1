$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ConfigPath = Join-Path $ProjectRoot "config.json"
if (-not (Test-Path -LiteralPath $ConfigPath)) { throw "config.json not found. Apply this update in the existing program folder." }
$Settings = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $Settings.ingest -or -not $Settings.analysis) { throw "Missing ingest/analysis settings." }
$BackupPath = Join-Path $ProjectRoot ("config.before-keithley-" + (Get-Date -Format "yyyyMMdd-HHmmssfff") + ".json")
Copy-Item -LiteralPath $ConfigPath -Destination $BackupPath
$Settings.ingest | Add-Member -NotePropertyName extensions -NotePropertyValue @(".xlsx", ".xls") -Force
if (-not ($Settings.ingest.PSObject.Properties.Name -contains "exclude_globs")) {
    $Settings.ingest | Add-Member -NotePropertyName exclude_globs -NotePropertyValue @()
}
$Settings.analysis | Add-Member -NotePropertyName auto_detect_axis -NotePropertyValue $true -Force
if (-not ($Settings.analysis.PSObject.Properties.Name -contains "transfer_models")) {
    $Settings.analysis | Add-Member -NotePropertyName transfer_models -NotePropertyValue @("linear")
}
$Encoding = [System.Text.UTF8Encoding]::new($false)
$TemporaryPath = $ConfigPath + ".tmp"
[System.IO.File]::WriteAllText($TemporaryPath, (($Settings | ConvertTo-Json -Depth 30) + [Environment]::NewLine), $Encoding)
Move-Item -LiteralPath $TemporaryPath -Destination $ConfigPath -Force
Write-Host "Keithley input: XLS/XLSX; automatic Vd/Vg axis selection. Restart the watcher."
Write-Host ("Previous config saved to " + $BackupPath)
