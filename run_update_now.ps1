$ErrorActionPreference = 'Stop'
$scriptName = if ($args -contains '--build-only' -or $args -contains '--external-only') { 'update_radar.py' } else { 'daily_pipeline.py' }
$scriptPath = Join-Path $PSScriptRoot $scriptName
$pythonCommand = Get-Command py.exe -ErrorAction SilentlyContinue
if (-not $pythonCommand) { $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue }
if ($pythonCommand) {
    $python = $pythonCommand.Source
} else {
    $profileRoot = [Environment]::GetFolderPath('UserProfile')
    if (-not $profileRoot) { $profileRoot = $env:USERPROFILE }
    $python = Join-Path $profileRoot '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
}
if (-not (Test-Path -LiteralPath $python)) { throw "找不到 Python：$python" }
& $python $scriptPath @args
exit $LASTEXITCODE
