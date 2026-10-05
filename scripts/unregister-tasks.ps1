$ErrorActionPreference = "Stop"
foreach ($TaskName in @("ResearchAutomation-Scan", "ResearchAutomation-Weekly", "ResearchAutomation-Backup")) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host ("Removed " + $TaskName)
    }
}
