# Atualiza a programação de cursos (turmas, datas, horários, valores e vagas) a partir do portal oficial de matrículas do Senac PB.
# Uso: powershell -File scripts\atualizar-cursos.ps1            (só consulta se a última consulta não foi hoje)
#      powershell -File scripts\atualizar-cursos.ps1 -Force     (consulta sempre; o portal ainda é tratado com intervalo mínimo)
# A consulta é feita ANTES da conversa: o robô nunca espera o portal durante um atendimento.
# Falha de rede nunca apaga dados: a última programação válida continua valendo (e o robô informa a data da consulta).
param(
    [switch]$Force,
    [switch]$Quiet
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$venvPython = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    Write-Host "Ambiente não encontrado. Rode scripts\setup.ps1 primeiro." -ForegroundColor Red
    exit 1
}

$mode = if ($Force) { '--force' } else { '--if-stale' }
if (-not $Quiet) { Write-Host "Atualizando a programação de cursos do Senac PB ($mode)..." }
try {
    & $venvPython -m backend.knowledge.portal $mode
    $code = $LASTEXITCODE
} catch {
    Write-Host "Não foi possível atualizar a programação: $($_.Exception.Message)" -ForegroundColor Yellow
    $code = 1
}
if ($code -ne 0 -and -not $Quiet) {
    Write-Host "A consulta falhou; o robô continua usando a última programação salva (com a data da consulta)." -ForegroundColor Yellow
}
exit $code
