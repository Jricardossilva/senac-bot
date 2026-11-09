@echo off
rem Inicia o SENAC BOT com dois cliques (instala o ambiente na primeira vez e abre o navegador).
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\run.ps1"
echo.
echo O SENAC BOT foi encerrado. Pressione qualquer tecla para fechar.
pause >nul
