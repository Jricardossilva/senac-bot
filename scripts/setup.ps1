# Instala o ambiente do SENAC BOT. Uso: powershell -File scripts\setup.ps1
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Fail($msg) { Write-Host "ERRO: $msg" -ForegroundColor Red; exit 1 }

# 1. Python 3.11+ (prefere o launcher "py"; usa "python" se não houver)
$pyCmd = $null; $pyArgs = @()
if (Get-Command py -ErrorAction SilentlyContinue) { $pyCmd = 'py'; $pyArgs = @('-3') }
elseif (Get-Command python -ErrorAction SilentlyContinue) { $pyCmd = 'python' }
if (-not $pyCmd) { Fail "Python não encontrado. Instale o Python 3.11 ou superior em python.org (marque 'Add python.exe to PATH')." }
$ver = & $pyCmd @pyArgs -c "import sys; print('%d.%d' % sys.version_info[:2])"
if ($LASTEXITCODE -ne 0 -or -not $ver) { Fail "Não foi possível executar o Python. Reinstale-o em python.org." }
Write-Host "Python do sistema: $ver"
$parts = $ver.Split('.')
if ([int]$parts[0] -lt 3 -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -lt 11)) {
    Fail "É necessário Python 3.11 ou superior (encontrado $ver)."
}

# 2. Ambiente virtual
$venvPython = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    Write-Host "Criando .venv ..."
    & $pyCmd @pyArgs -m venv (Join-Path $root '.venv')
    if ($LASTEXITCODE -ne 0) { Fail "Falha ao criar o ambiente virtual." }
} else {
    Write-Host ".venv já existe."
}

# 3. Ferramentas de instalação
& $venvPython -m pip install --upgrade pip setuptools wheel
if ($LASTEXITCODE -ne 0) { Fail "Falha ao atualizar pip/setuptools/wheel. Verifique a internet." }

# 4. Dependências
& $venvPython -m pip install -r (Join-Path $root 'requirements.txt')
if ($LASTEXITCODE -ne 0) { Fail "Falha ao instalar requirements.txt. Verifique a internet e a mensagem acima." }

# 5. Verificação
& $venvPython -c "import fastapi, uvicorn, dotenv, pytest, httpx, websockets; from google import genai; print('Imports OK')"
if ($LASTEXITCODE -ne 0) { Fail "Dependências instaladas, mas a verificação de imports falhou." }
& $venvPython -m pip check
if ($LASTEXITCODE -ne 0) { Write-Host "AVISO: pip check encontrou dependências inconsistentes." -ForegroundColor Yellow }

# .env
$envFile = Join-Path $root '.env'
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $root '.env.example') $envFile
    Write-Host "Criado .env a partir de .env.example. Preencha GEMINI_API_KEY para ativar o Gemini (opcional)."
}

Write-Host "Setup concluído. Para iniciar: dê dois cliques em iniciar.bat ou execute scripts\run.ps1" -ForegroundColor Green
