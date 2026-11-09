# Inicia o SENAC BOT. Uso: powershell -File scripts\run.ps1 [-NoBrowser] [-Port 8000]
# Na primeira execução instala o ambiente sozinho e, ao final da inicialização, abre o navegador.
param(
    [switch]$NoBrowser,
    [int]$Port = 0
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Fail($msg) { Write-Host "ERRO: $msg" -ForegroundColor Red; exit 1 }

# 1. Ambiente virtual (instala automaticamente se ainda não existir)
$venvPython = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    Write-Host "Primeira execução: preparando o ambiente (pode levar alguns minutos)..." -ForegroundColor Yellow
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'setup.ps1')
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $venvPython)) {
        Fail "A instalação não foi concluída. Leia a mensagem acima e execute scripts\setup.ps1 novamente."
    }
}

# 2. .env (a aplicação funciona sem chave do Gemini)
$envFile = Join-Path $root '.env'
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $root '.env.example') $envFile
    Write-Host "Criado .env a partir de .env.example (sem chave do Gemini: respostas locais)." -ForegroundColor Yellow
}

# 3. Host e porta (padrões, depois .env, depois parâmetro)
$hostAddr = '127.0.0.1'; $portValue = '8000'; $hasKey = $false
foreach ($line in Get-Content $envFile) {
    if ($line -match '^\s*SENAC_HOST\s*=\s*(.+?)\s*$') { $hostAddr = $Matches[1] }
    if ($line -match '^\s*SENAC_PORT\s*=\s*(.+?)\s*$') { $portValue = $Matches[1] }
    if ($line -match '^\s*GEMINI_API_KEY\s*=\s*\S+') { $hasKey = $true }
}
if ($Port -gt 0) { $portValue = "$Port" }
if ($portValue -notmatch '^\d+$') { Fail "SENAC_PORT inválida no .env: '$portValue'." }

# 4. Porta livre?
try {
    $probe = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Parse($hostAddr), [int]$portValue)
    $probe.Start(); $probe.Stop()
} catch {
    Fail "A porta $portValue já está em uso (talvez o SENAC BOT já esteja aberto). Feche o outro programa ou altere SENAC_PORT no .env."
}

$displayHost = if ($hostAddr -eq '127.0.0.1') { 'localhost' } else { $hostAddr }
$url = "http://${displayHost}:${portValue}"
Write-Host ""
Write-Host "SENAC BOT em $url  (Ctrl+C para encerrar)" -ForegroundColor Green
if ($hasKey) { Write-Host "Gemini: chave encontrada no .env." } else { Write-Host "Gemini: sem chave; o robô usará respostas locais." -ForegroundColor Yellow }
Write-Host "Dica: na tela do operador, clique em 'Verificar sistema' antes de abrir ao público."

# 5. Abre o navegador quando o servidor estiver pronto
if (-not $NoBrowser) {
    Start-Job -ArgumentList $url -ScriptBlock {
        param($address)
        for ($i = 0; $i -lt 40; $i++) {
            Start-Sleep -Milliseconds 500
            try {
                Invoke-WebRequest -Uri "$address/health" -UseBasicParsing -TimeoutSec 2 | Out-Null
                Start-Process $address
                return
            } catch { }
        }
    } | Out-Null
}

# 6. Servidor
& $venvPython -m uvicorn backend.main:app --host $hostAddr --port $portValue
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERRO: o servidor encerrou com código $LASTEXITCODE. Causas comuns: dependências ausentes (rode scripts\setup.ps1) ou erro de configuração no .env." -ForegroundColor Red
    exit $LASTEXITCODE
}
