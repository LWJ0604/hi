$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ConfigPath = Join-Path $ProjectRoot "config.json"
if (-not (Test-Path -LiteralPath $ConfigPath)) { throw "config.json not found. Run this in the existing installation folder." }
$Settings = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $Settings.ingest) { throw "config.json has no ingest settings." }
$BackupPath = Join-Path $ProjectRoot ("config.before-excel-only-" + (Get-Date -Format "yyyyMMdd-HHmmssfff") + ".json")
Copy-Item -LiteralPath $ConfigPath -Destination $BackupPath
$Settings.ingest | Add-Member -NotePropertyName extensions -NotePropertyValue @(".xlsx", ".xls") -Force
if (-not ($Settings.ingest.PSObject.Properties.Name -contains "exclude_globs")) {
    $Settings.ingest | Add-Member -NotePropertyName exclude_globs -NotePropertyValue @()
}
$TemporaryPath = $ConfigPath + ".tmp"
$Encoding = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllText($TemporaryPath, (($Settings | ConvertTo-Json -Depth 30) + [Environment]::NewLine), $Encoding)
Move-Item -LiteralPath $TemporaryPath -Destination $ConfigPath -Force
Write-Host "Input filter now accepts .xlsx and .xls only. Restart the watcher."
Write-Host ("Previous config saved to " + $BackupPath)
