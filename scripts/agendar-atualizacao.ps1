# Cria (ou remove) uma tarefa diária do Windows que atualiza a programação de cursos, mesmo com o SENAC BOT fechado.
# Uso: powershell -File scripts\agendar-atualizacao.ps1                 (todo dia às 06:00)
#      powershell -File scripts\agendar-atualizacao.ps1 -Hora 05:30
#      powershell -File scripts\agendar-atualizacao.ps1 -Remover
# Roda como o usuário atual, sem privilégios elevados. A atualização também acontece em toda inicialização do robô
# (scripts\run.ps1) e em segundo plano enquanto ele estiver aberto; a tarefa só garante a programação do dia com ele fechado.
param(
    [string]$Hora = '06:00',
    [switch]$Remover
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$taskName = 'SENAC BOT - atualizar programacao de cursos'

if ($Remover) {
    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        Write-Host "Tarefa removida." -ForegroundColor Green
    } else {
        Write-Host "A tarefa não existe."
    }
    exit 0
}

if ($Hora -notmatch '^([01]\d|2[0-3]):[0-5]\d$') {
    Write-Host "ERRO: informe a hora no formato HH:mm (ex.: 06:00)." -ForegroundColor Red
    exit 1
}
$script = Join-Path $root 'scripts\atualizar-cursos.ps1'
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -WorkingDirectory $root `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`" -Force -Quiet"
$trigger = New-ScheduledTaskTrigger -Daily -At $Hora
# Se o computador estava desligado na hora marcada, roda assim que for possível.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings `
    -Description 'Consulta o portal oficial de matrículas do Senac PB e salva turmas, datas, horários, valores e vagas.' -Force | Out-Null
Write-Host "Tarefa criada: todos os dias às $Hora ($taskName)." -ForegroundColor Green
