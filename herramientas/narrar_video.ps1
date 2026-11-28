param(
    [string]$Guion = 'docs/video-guion.json',
    [string]$Salida = 'entrega/audio',
    [string]$Voz = 'Microsoft Sabina Desktop'
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$escenas = Get-Content -LiteralPath $Guion -Raw -Encoding utf8 | ConvertFrom-Json
New-Item -ItemType Directory -Path $Salida -Force | Out-Null
$narrador = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $narrador.SelectVoice($Voz)
    $narrador.Rate = 0
    foreach ($escena in $escenas) {
        $destino = Join-Path (Resolve-Path -LiteralPath $Salida) ($escena.id + '.wav')
        $narrador.SetOutputToWaveFile($destino)
        $narrador.Speak($escena.narracion)
        $narrador.SetOutputToNull()
        Write-Output ('Narrada: ' + $escena.id)
    }
} finally {
    $narrador.Dispose()
}
