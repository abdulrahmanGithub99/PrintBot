# Build script: PyInstaller one-folder build + (optional) Inno Setup installer
# Usage: powershell -ExecutionPolicy Bypass -File build.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "==> Installing build requirements..." -ForegroundColor Cyan
pip install -r "$root\requirements.txt" pyinstaller 2>&1 | Out-Null

Write-Host "==> Building with PyInstaller..." -ForegroundColor Cyan
Push-Location $root
try {
    pyinstaller --noconfirm --clean --windowed --name PrintBot `
        --icon PrintBot.ico `
        --add-data "SumatraPDF.exe;." `
        --add-data "PrintBot.ico;." `
        --hidden-import win32print `
        app/main.py
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
} finally {
    Pop-Location
}

Write-Host "==> Build complete: $root\dist\PrintBot" -ForegroundColor Green

# Inno Setup (اختياري)
$iscc = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
    "${env:LOCALAPPDATA}\Programs\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($iscc) {
    Write-Host "==> Running Inno Setup compiler..." -ForegroundColor Cyan
    & $iscc "$root\installer\PrintBot.iss"
    if ($LASTEXITCODE -eq 0) {
        Write-Host "==> Installer created: $root\PrintBotSetup-1.1.0.exe" -ForegroundColor Green
    }
} else {
    Write-Host "Inno Setup not found — skipping installer. Install it from https://jrsoftware.org/isinfo.php" -ForegroundColor Yellow
    Write-Host "You can distribute the portable folder: $root\dist\PrintBot" -ForegroundColor Yellow
}
