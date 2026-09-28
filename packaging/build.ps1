$ErrorActionPreference = "Stop"

Set-Location (Join-Path $PSScriptRoot "..")
python -m pip install -r requirements.txt
python packaging/prepare_tiktoken_cache.py
pyinstaller --clean --noconfirm packaging/OneShot.spec

$isccPath = (Get-Command iscc -ErrorAction SilentlyContinue).Source
if (-not $isccPath) {
    $knownPaths = @(
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles(x86)\Inno Setup 6\ISCC.exe"
    )
    $knownPath = $knownPaths | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($knownPath) {
        $isccPath = $knownPath
    }
}
if (-not $isccPath) {
    throw "Inno Setup is required. Install it from https://jrsoftware.org/isinfo.php and ensure iscc.exe is on PATH."
}

& $isccPath packaging/installer.iss
Write-Host "Installer created in dist/installer"
Write-Host "The generated files are unsigned; office-managed devices may still require IT approval or code signing."
