r"""Teste geral da interface no Edge headless: telas, simulador, sensores, conversa por voz, emergência e layout móvel.

Uso (servidor em execução):  .\.venv\Scripts\python.exe tests\e2e\browser_smoke.py http://127.0.0.1:8000/
A voz é simulada pelos dublês de _browser.py.
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
b = Browser(BASE, 9300, options={"autoFinish": 150}, timings={"resumeDelayMs": 150, "restartDelayMs": 80, "errorPauseMs": 400})
try:
    attr = lambda sel, a: b.js(f"document.querySelector({json.dumps(sel)}).{a}")

    R.check("conexão", attr("#connection-label", "textContent"), "Sistema conectado")
    R.check("avatar visitante neutro", attr("#visitor-robot", "dataset.expression"), "neutral")
    R.check("avatar montado a partir do modelo único (SVG)", b.js("document.querySelectorAll('.robot svg.robot-svg').length"), 2)
    R.check("logotipos oficiais carregados", b.js("[...document.querySelectorAll('img.brand-logo, img.stage-logo, img.footer-logo')].every(i => i.complete && i.naturalWidth > 0)"), True)

    for view in ("operator", "simulator", "diagnostics", "visitor"):
        b.view(view)
        R.check(f"tela {view} visível", b.js(f"!document.getElementById('{view}').hidden"), True)

    # simulador: expressões e movimentos
    b.view("simulator")
    for action, a in (("happy", "expression"), ("surprised", "expression"), ("sad", "expression"), ("disconnected", "expression"),
                      ("neutral", "expression"), ("look_left", "action"), ("tilt_head", "action"),
                      ("wheels_backward", "action"), ("stop", "action")):
        b.click(f".action-chip[data-action={action}]")
        time.sleep(0.5)
        R.check(f"chip {action}", attr("#simulator-robot", f"dataset.{a}"), action)
    b.click(".action-chip[data-action=wave]")
    time.sleep(0.4)
    R.check("wave ativo", attr("#simulator-robot", "dataset.action"), "wave")
    time.sleep(3.6)
    R.check("wave volta a idle (backend)", attr("#simulator-robot", "dataset.action"), "idle")

    # sensor: obstáculo bloqueia avanço
    b.js("(()=>{const s=document.querySelector('#sensor-distance');s.value=10;s.dispatchEvent(new Event('input',{bubbles:true}));})()")
    time.sleep(0.8)
    R.check("obstáculo detectado", attr("#sensor-obstacle", "textContent"), "Obstáculo à frente")
    b.click(".action-chip[data-action=wheels_forward]")
    time.sleep(0.5)
    R.check("avanço bloqueado (mensagem)", "Obstáculo" in (attr("#simulator-feedback", "textContent") or ""), True)
    R.check("sensor-dot vermelho via data-obstacle", attr("#simulator-robot", "dataset.obstacle"), "true")
    b.js("(()=>{const s=document.querySelector('#sensor-distance');s.value=150;s.dispatchEvent(new Event('input',{bubbles:true}));})()")
    time.sleep(0.6)

    # conversa por voz: saudação local + reação do robô
    b.view("visitor")
    R.check("visitante: botão INICIAR CONVERSA e nenhum campo de texto",
            (b.button_label(), b.js("document.querySelectorAll('#visitor input, #visitor textarea').length")), ("INICIAR CONVERSA", 0))
    b.click("#conversation-button")
    R.check("conversa inicia e passa a ouvir", b.wait_for("__fake.running === true && document.querySelector('#visitor-state').dataset.state === 'Ouvindo'", 10), True)
    b.js("__fake.hear('Olá')")
    R.check("resposta aparece nas legendas",
            b.wait_for("document.querySelectorAll('#messages .bot-message').length === 2", 10), True)
    R.check("origem da resposta oculta ao visitante", b.js("getComputedStyle(document.querySelector('#messages .message-source')).display"), "none")
    R.check("robô reagiu (cumprimentar)", b.js("['wave','idle'].includes(document.querySelector('#visitor-robot').dataset.action)"), True)
    R.check("voz falada com a resposta", b.wait_for("__fake.spoken.length === 1 && __fake.spoken[0].startsWith('Olá')", 5), True)
    b.click("#conversation-button")
    R.check("encerrar conversa libera o microfone", b.wait_for("__fake.running === false", 5) and b.js("__fake.mic.opened === __fake.mic.stopped"), True)

    # emergência
    b.view("operator")
    b.click("#emergency-button")
    time.sleep(0.6)
    R.check("emergência ativa", attr("#visitor-robot", "dataset.emergency"), "true")
    R.check("liberar visível", b.js("!document.querySelector('#emergency-release').hidden"), True)
    b.click("#emergency-release")
    time.sleep(0.6)
    R.check("emergência liberada", attr("#visitor-robot", "dataset.emergency"), "false")

    # diagnóstico
    b.view("diagnostics")
    time.sleep(1)
    R.check("diagnóstico: contexto seguro", attr("#diag-secure", "textContent"), "Sim (localhost)")

    # layout responsivo: sem rolagem horizontal
    b.send("Emulation.setDeviceMetricsOverride", width=390, height=800, deviceScaleFactor=1, mobile=True)
    time.sleep(0.5)
    for view in ("visitor", "operator", "simulator", "diagnostics"):
        b.view(view)
        time.sleep(0.3)
        R.check(f"sem rolagem horizontal ({view}, 390px)", b.js("document.documentElement.scrollWidth <= window.innerWidth + 1"), True)

    R.check("sem erros de JavaScript", b.real_errors(), [])
finally:
    b.close()
sys.exit(R.summary())
