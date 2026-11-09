r"""Prompt 8 + conversa por voz no Edge headless: verificação do sistema, modos de hardware e demonstração.

Uso (servidor em execução; leva cerca de 1 minuto):
    .\.venv\Scripts\python.exe tests\e2e\browser_demo.py http://127.0.0.1:8000/
A voz é simulada pelos dublês de _browser.py (a síntese termina sozinha em 150 ms). Na janela de perguntas da
demonstração o "visitante" fala pelo reconhecimento simulado.
"""
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _browser import Browser, Reporter, base_url  # noqa: E402

BASE = base_url()
R = Reporter()
urllib.request.urlopen(urllib.request.Request(BASE.rstrip("/") + "/api/session/stop", method="POST", data=b"{}",
                                              headers={"Content-Type": "application/json"}))
b = Browser(BASE, 9360, options={"autoFinish": 150}, timings={"resumeDelayMs": 150, "restartDelayMs": 80, "errorPauseMs": 400})
try:
    # ---- verificação do sistema ----
    b.view("operator")
    R.check("verificação automática ao abrir o operador", b.wait_for("document.querySelectorAll('#preflight-list li').length >= 7", 30), True)
    items = b.js("[...document.querySelectorAll('#preflight-list li strong')].map(e => e.textContent)")
    for label in ("Internet", "Gemini (IA)", "Hardware", "Parada de emergência", "Microfone", "Reconhecimento de voz", "Voz sintetizada"):
        R.check(f"item '{label}'", label in items, True)
    R.check("resumo indica prontidão", b.js("document.querySelector('#preflight-summary').dataset.ready"), "true")
    R.check("itens com aviso trazem ação", b.js("[...document.querySelectorAll('#preflight-list li[data-status=warning]')].every(li => li.querySelector('small'))"), True)

    # ---- teste de mensagem do operador (fora da tela do visitante) ----
    b.js("(()=>{const i=document.querySelector('#op-test-message');i.value='Quem é você?';document.querySelector('#op-test-form').requestSubmit();})()")
    R.check("operador testa respostas por texto", b.wait_for("document.querySelector('#op-test-reply').textContent.includes('SENAC BOT')", 10), True)

    # ---- modos de hardware ----
    b.click("[data-hardware-mode=physical]")
    b.wait_for("document.querySelector('#hardware-feedback').classList.contains('error')", 5)
    R.check("modo físico: mensagem clara", "ainda não está disponível" in b.js("document.querySelector('#hardware-feedback').textContent"), True)
    R.check("modo físico: simulador segue ativo", b.js("document.querySelector('#hardware-state').textContent"), "Simulador local")
    b.click("[data-hardware-mode=simulation]")
    b.wait_for("!document.querySelector('#hardware-feedback').classList.contains('error')", 5)
    R.check("ativar simulador limpa o erro", b.js("document.querySelector('[data-hardware-mode=simulation]').classList.contains('selected')"), True)

    # ---- demonstração completa ----
    b.click("#start-demo")
    R.check("demonstração abre a tela do visitante", b.wait_for("!document.getElementById('visitor').hidden", 5), True)
    R.check("botões: iniciar desabilitado, encerrar habilitado",
            b.wait_for("document.querySelector('#start-demo').disabled && !document.querySelector('#stop-demo').disabled", 5), True)
    R.check("botão da conversa informa demonstração em andamento", b.button_label(), "DEMONSTRAÇÃO EM ANDAMENTO")
    R.check("abre janela de perguntas", b.wait_for("!document.querySelector('#demo-skip').hidden", 40), True)
    R.check("fala de abertura exibida com origem", b.js("document.querySelector('#messages .message-source[data-source=demo]')?.textContent"), "Demonstração")
    R.check("janela de perguntas ouve o visitante (sem clique)", b.wait_for("__fake.running === true", 10), True)
    b.js("__fake.hear('O que é robótica?')")
    R.check("pergunta falada respondida durante a demonstração",
            b.wait_for("[...document.querySelectorAll('#messages .bot-message p')].some(p => p.textContent.startsWith('Robótica'))", 10), True)
    R.check("escuta retomada sozinha depois da resposta", b.wait_for("__fake.running === true", 10), True)
    b.click("#demo-skip")
    R.check("continuar demonstração encerra a escuta", b.wait_for("__fake.running === false", 8), True)
    R.check("desafio proposto (local)", b.wait_for("[...document.querySelectorAll('#messages .bot-message p')].some(p => p.textContent.startsWith('Desafio'))", 20), True)
    seen = set()
    end = time.time() + 45
    while time.time() < end and not b.js("document.querySelector('#stop-demo').disabled"):
        seen.add(b.js("document.querySelector('#visitor-robot').dataset.expression"))
        seen.add(b.js("document.querySelector('#visitor-robot').dataset.action"))
        time.sleep(0.2)
    R.check("expressões executadas", {"surprised", "sad"} <= seen, True)
    R.check("movimentos executados", {"look_left", "tilt_head", "spin"} <= seen, True)
    R.check("demonstração termina sozinha", b.js("document.querySelector('#stop-demo').disabled"), True)
    R.check("despedida exibida", b.js("[...document.querySelectorAll('#messages .bot-message p')].some(p => p.textContent.startsWith('Foi um prazer'))"), True)
    time.sleep(0.8)
    R.check("robô volta ao neutro", b.js("document.querySelector('#visitor-robot').dataset.expression + '/' + document.querySelector('#visitor-robot').dataset.action"), "neutral/idle")
    R.check("botão da conversa volta a INICIAR CONVERSA", b.button_label(), "INICIAR CONVERSA")
    R.check("microfone liberado depois da demonstração", (b.js("__fake.running"), b.js("__fake.mic.opened === __fake.mic.stopped")), (False, True))
    events = b.js("fetch('/api/status').then(r => r.json()).then(s => s.events)")
    R.check("eventos registram início e fim", {"Demonstração iniciada.", "Demonstração encerrada."} <= set(events), True)

    # ---- encerrar no meio ----
    b.click("#start-demo")
    b.wait_for("document.querySelector('#start-demo').disabled", 5)
    time.sleep(2)
    count_before = b.js("document.querySelectorAll('#messages .message').length")
    b.click("#stop-demo")
    R.check("encerrar demonstração no meio", b.wait_for("document.querySelector('#stop-demo').disabled && !document.querySelector('#start-demo').disabled", 8), True)
    time.sleep(2)
    R.check("roteiro para de falar após encerrar", b.js("document.querySelectorAll('#messages .message').length") - count_before <= 1, True)

    # ---- emergência encerra a demonstração ----
    b.click("#start-demo")
    b.wait_for("document.querySelector('#start-demo').disabled", 5)
    b.view("operator")
    b.click("#emergency-button")
    R.check("emergência encerra a demonstração", b.wait_for("document.querySelector('#stop-demo').disabled", 8), True)
    R.check("iniciar demonstração bloqueado na emergência", b.js("document.querySelector('#start-demo').disabled"), True)
    b.click("#emergency-release")
    b.wait_for("!document.querySelector('#start-demo').disabled", 8)
    R.check("demonstração liberada após a emergência", b.js("document.querySelector('#start-demo').disabled"), False)
    b.js("fetch('/api/session/stop',{method:'POST'})")

    R.check("sem erros de JavaScript", b.real_errors(), [])
finally:
    b.close()
sys.exit(R.summary())
