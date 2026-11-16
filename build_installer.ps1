# Build ALIVE-Setup-<version>.exe from the folder build.
# Requires Inno Setup 6 (winget install JRSoftware.InnoSetup).
# Usage: powershell -ExecutionPolicy Bypass -File build_installer.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path "dist\ALIVE\ALIVE.exe")) {
    Write-Host "dist\ALIVE\ALIVE.exe not found: building it first."
    python -m PyInstaller --noconfirm --clean --distpath dist --workpath build ALIVE.spec
}

$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
          "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
          "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 not found. Install it: winget install JRSoftware.InnoSetup" }

& $iscc "installer.iss"
if ($LASTEXITCODE -ne 0) { throw "ISCC failed with exit code $LASTEXITCODE" }
Get-ChildItem dist -Filter "ALIVE-Setup-*.exe" | ForEach-Object {
    Write-Host ("Built {0}  ({1:N1} MB)" -f $_.FullName, ($_.Length / 1MB))
}
