# Atualiza a base de conhecimento a partir das fontes oficiais do Senac.
# Uso: powershell -File scripts\atualizar-conhecimento.ps1 [-Report] [-Only pb-psg,pb-unidades] [-Ack pb-unidades]
# Respeita o robots.txt, consulta apenas páginas públicas e espaça as requisições.
param(
    [switch]$Report,
    [string[]]$Only,
    [string[]]$Ack
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    Write-Host "ERRO: .venv não encontrado. Execute primeiro: powershell -File scripts\setup.ps1" -ForegroundColor Red
    exit 1
}
$argsList = @('-m', 'backend.knowledge.update')
if ($Report) { $argsList += '--report' }
if ($Only) { $argsList += '--only'; $argsList += $Only }
if ($Ack) { $argsList += '--ack'; $argsList += $Ack }
& $python @argsList
exit $LASTEXITCODE
