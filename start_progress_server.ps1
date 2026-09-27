$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$profileRoot = [Environment]::GetFolderPath('UserProfile')
$candidates = @(
    (Get-Command py.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1),
    (Get-Command python.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1),
    (Join-Path $profileRoot ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe")
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }

if (-not $candidates) {
    Write-Host "没有找到 Python。请先安装 Python 3.10 或更高版本。" -ForegroundColor Red
    Read-Host "按回车退出"
    exit 1
}

Set-Location -LiteralPath $projectRoot
& $candidates[0] (Join-Path $projectRoot "progress_server.py")
