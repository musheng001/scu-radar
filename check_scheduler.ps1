$ErrorActionPreference = 'Stop'
$taskName = 'SCU Radar Auto Update'
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if (-not $task) {
    [pscustomobject]@{ installed = $false; task = $taskName; message = '未找到计划任务；请运行 install_scheduler.ps1。' } | ConvertTo-Json -Compress
    exit 0
}
$info = Get-ScheduledTaskInfo -TaskName $taskName
[pscustomobject]@{
    installed = $true
    task = $taskName
    state = [string]$task.State
    lastRun = $info.LastRunTime.ToString('o')
    nextRun = $info.NextRunTime.ToString('o')
    lastTaskResult = $info.LastTaskResult
} | ConvertTo-Json -Compress
