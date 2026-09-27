$ErrorActionPreference = 'Stop'
$dryRun = $args -contains '-DryRun'
$taskName = 'SCU Radar Auto Update'
$scriptPath = Join-Path $PSScriptRoot 'daily_pipeline.py'
$pythonCommand = Get-Command py.exe -ErrorAction SilentlyContinue
if (-not $pythonCommand) { $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue }
if ($pythonCommand) {
    $python = $pythonCommand.Source
    $pythonSource = 'PATH'
} else {
    $profileRoot = [Environment]::GetFolderPath('UserProfile')
    if (-not $profileRoot) { $profileRoot = $env:USERPROFILE }
    $bundled = Join-Path $profileRoot '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    if (-not (Test-Path -LiteralPath $bundled)) {
        throw '找不到 py.exe、python.exe 或当前 Codex bundled Python。请先安装 Python，或手动运行 update_radar.py。'
    }
    $python = $bundled
    $pythonSource = 'Codex bundled runtime'
}
if ($dryRun) {
    $nextRun = (Get-Date).Date.AddHours(7).AddMinutes(30)
    if ($nextRun -le (Get-Date)) { $nextRun = $nextRun.AddDays(1) }
    [pscustomobject]@{ dryRun = $true; task = $taskName; python = $python; pythonSource = $pythonSource; script = $scriptPath; nextRun = $nextRun.ToString('o'); schedule = 'daily 07:30 Asia/Shanghai' } | ConvertTo-Json -Compress
    exit 0
}
try {
    $action = New-ScheduledTaskAction -Execute $python -Argument ('"' + $scriptPath + '"') -WorkingDirectory $PSScriptRoot
    $trigger = New-ScheduledTaskTrigger -Daily -At '07:30'
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description 'Daily public-source pipeline for SCU Radar: collect, preserve snapshots, rebuild, and log health.' -Force | Out-Null
} catch {
    $advancedError = $_.Exception.Message
    $taskCommand = '"' + $python + '" "' + $scriptPath + '"'
    & schtasks.exe /Create /SC DAILY /ST 07:30 /TN $taskName /TR $taskCommand /F | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Windows 的高级接口和普通用户接口都拒绝注册任务。未修改已有任务。高级接口：$advancedError"
    }
}
Write-Output "Installed scheduled task: $taskName"
Write-Output "Python: $python ($pythonSource)"
$installedTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($installedTask) { Write-Output "Next run: $($installedTask.Triggers[0].StartBoundary)" }
