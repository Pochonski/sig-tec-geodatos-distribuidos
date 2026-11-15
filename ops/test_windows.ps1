param(
    [string]$Python = "$PSScriptRoot\.venv-win\Scripts\python.exe",
    [string]$Config = "",
    [switch]$Integration
)
$ErrorActionPreference = "Stop"
if ($env:OS -ne "Windows_NT") { throw "Esta validación requiere Windows real." }
if (-not (Test-Path $Python)) { throw "Crear ops/.venv-win e instalar ops/requirements.txt primero." }
$previousUtf8 = $env:PYTHONUTF8
$previousIo = $env:PYTHONIOENCODING
$previousConfig = $env:SIGTEC_OPS_CONFIG
$passed = $false
try {
    $env:PYTHONUTF8 = "0"
    $env:PYTHONIOENCODING = "cp1252"
    & $Python -B "$PSScriptRoot\test_utf8.py"
    if ($LASTEXITCODE -ne 0) { throw "Fallaron las pruebas UTF-8." }
    if ($Integration) {
        if (-not $Config) { throw "Integration requiere un inventario de laboratorio explícito." }
        $env:SIGTEC_OPS_CONFIG = (Resolve-Path $Config).Path
        & $Python -c "import json,sys; assert json.load(open(sys.argv[1],encoding='utf-8-sig'))['project']=='sig-tec-rejoin-lab'" $env:SIGTEC_OPS_CONFIG
        if ($LASTEXITCODE -ne 0) { throw "La integración de prueba solo acepta el laboratorio." }
        & $Python -B "$PSScriptRoot\migrate.py"
        if ($LASTEXITCODE -ne 0) { throw "Fallaron las migraciones del laboratorio." }
        & $Python -B "$PSScriptRoot\integration_checks.py"
        if ($LASTEXITCODE -ne 0) { throw "Falló la integración." }
    }
    $passed = $true
} finally {
    $env:PYTHONUTF8 = $previousUtf8
    $env:PYTHONIOENCODING = $previousIo
    $env:SIGTEC_OPS_CONFIG = $previousConfig
    $result = @{
        executed_at_utc = [DateTime]::UtcNow.ToString("o")
        platform = "Windows"
        os_version = [Environment]::OSVersion.VersionString
        powershell = $PSVersionTable.PSVersion.ToString()
        utf8_passed = $passed
        integration_requested = [bool]$Integration
        status = $(if ($passed) { "passed" } else { "failed" })
    }
    $text = ($result | ConvertTo-Json -Depth 4) + "`n"
    [IO.File]::WriteAllText("$PSScriptRoot\windows-results.json", $text, [Text.UTF8Encoding]::new($false))
}
