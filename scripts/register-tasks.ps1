param([string]$WeeklyTime = "18:00", [string]$BackupTime = "19:00")
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Runner = Join-Path $PSScriptRoot "run-job.ps1"
if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot ".venv\Scripts\python.exe"))) {
    throw "Run Setup.cmd first."
}
if ($Runner.Contains('"')) { throw "Unsupported quote in installation path." }
$Account = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$Principal = New-ScheduledTaskPrincipal -UserId $Account -LogonType Interactive -RunLevel Limited
$Settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2)
$ScanTrigger = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(1)) -RepetitionInterval (New-TimeSpan -Minutes 1)
$WeeklyTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Friday -At $WeeklyTime
$BackupTrigger = New-ScheduledTaskTrigger -Daily -At $BackupTime
$Tasks = @(
    @{ Name = "ResearchAutomation-Scan"; Job = "scan"; Trigger = $ScanTrigger },
    @{ Name = "ResearchAutomation-Weekly"; Job = "weekly"; Trigger = $WeeklyTrigger },
    @{ Name = "ResearchAutomation-Backup"; Job = "backup"; Trigger = $BackupTrigger }
)
foreach ($Task in $Tasks) {
    $Arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + $Runner + '" -Job ' + $Task.Job
    $Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $Arguments -WorkingDirectory $ProjectRoot
    Register-ScheduledTask -TaskName $Task.Name -Action $Action -Trigger $Task.Trigger -Settings $Settings -Principal $Principal -Description "Local research pipeline; current user must be signed in." -Force | Out-Null
    Write-Host ("Registered " + $Task.Name)
}
Write-Host "Schedules use this PC's local clock and run while the current user is signed in."
