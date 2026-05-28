param(
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host "=== SpaceLens Windows build ==="
Write-Host "Working directory: $Root"

function Stop-SpaceLensProcesses {
    $names = @("SpaceLens", "QtWebEngineProcess")
    foreach ($name in $names) {
        $procs = Get-Process -Name $name -ErrorAction SilentlyContinue
        if ($procs) {
            Write-Host "Stopping running process: $name"
            $procs | Stop-Process -Force -ErrorAction SilentlyContinue
        }
    }
}

function Remove-WithRetry {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [int]$Retries = 6
    )

    if (-not (Test-Path $Path)) {
        return
    }

    for ($i = 1; $i -le $Retries; $i++) {
        try {
            Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
            return
        } catch {
            if ($i -eq $Retries) {
                Write-Host ""
                Write-Host "Failed to remove: $Path" -ForegroundColor Red
                Write-Host "This usually means SpaceLens.exe is still running, Windows Explorer is previewing the folder, or antivirus is scanning it." -ForegroundColor Yellow
                Write-Host "Close SpaceLens, close Explorer windows opened inside dist, then run this script again." -ForegroundColor Yellow
                throw
            }
            Start-Sleep -Milliseconds (500 * $i)
            Stop-SpaceLensProcesses
        }
    }
}

Stop-SpaceLensProcesses
Start-Sleep -Milliseconds 500

Remove-WithRetry (Join-Path $Root "dist\SpaceLens")
Remove-WithRetry (Join-Path $Root "build\build_windows")

if (-not $SkipInstall) {
    Write-Host "Installing build dependencies..."
    python -m pip install -r requirements.txt pyinstaller
}

Write-Host "Running PyInstaller..."
pyinstaller --noconfirm --clean build_windows.spec

Write-Host ""
Write-Host "=== Build complete ===" -ForegroundColor Green
Write-Host "Output: dist\SpaceLens\"
