r"""Conversa por voz no Edge headless com dublês de voz (veja _browser.py).

Uso (servidor em execução):  .\.venv\Scripts\python.exe tests\e2e\browser_conversation.py http://127.0.0.1:8000/
Cobre: iniciar conversa, permissão, perguntas consecutivas sem novo toque, resposta falada, retomada automática,
interrupção, encerramento, microfone indisponível, permissão negada, falhas do reconhecimento e voz do próprio robô.
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
FAST = {"resumeDelayMs": 150, "restartDelayMs": 80, "errorPauseMs": 400, "idleTimeoutMs": 60000}


def api(path: str, method: str = "POST"):
    req = urllib.request.Request(BASE.rstrip("/") + path, method=method, data=b"{}" if method == "POST" else None,
                                 headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req))


def listening(b: Browser, timeout: float = 10) -> bool:
    return b.wait_for("__fake.running === true && document.querySelector('#visitor-state').dataset.state === 'Ouvindo'", timeout)


def ask(b: Browser, text: str, finish: bool = True) -> None:
    """O visitante fala; espera a resposta ser falada e (opcionalmente) a fala terminar."""
    assert listening(b), f"não estava ouvindo antes de: {text}"
    b.js(f"__fake.hear({json.dumps(text)})")
    b.wait_for("__fake.ttsCurrent !== null", 10)
    if finish:
        b.js("__fake.finishSpeech()")


def fresh(**kwargs) -> Browser:
    api("/api/session/stop")
    return Browser(BASE, kwargs.pop("port"), timings=kwargs.pop("timings", FAST), **kwargs)


# ------------------------------------------------------------------ fluxo principal
b = fresh(port=9501)
try:
    R.check("tela do visitante não tem campo de texto, formulário nem botão enviar",
            b.js("document.querySelectorAll('#visitor input, #visitor textarea, #visitor form, #send-button').length"), 0)
    R.check("botão principal: INICIAR CONVERSA", b.button_label(), "INICIAR CONVERSA")
    R.check("estado inicial: aguardando início", b.state(), "Aguardando")
    R.check("nenhum elemento técnico de IA para o visitante",
            b.js("/gemini|contingência|resposta local/i.test(document.getElementById('visitor').innerText)"), False)

    b.click("#conversation-button")
    R.check("iniciar: solicita permissão e passa a ouvir", listening(b), True)
    R.check("botão vira ENCERRAR CONVERSA", b.button_label(), "ENCERRAR CONVERSA")
    R.check("permissão: microfone aberto e fechado na hora (sem manter captura)",
            b.js("__fake.mic.opened >= 1 && __fake.mic.opened === __fake.mic.stopped"), True)
    R.check("sessão aberta no servidor", b.js("__fake.sessions[0]"), "start")
    R.check("avatar com animação de escuta", b.js("document.querySelector('#visitor-robot').dataset.voice"), "listening")
    R.check("legenda de boas-vindas", "INICIAR CONVERSA" in b.js("document.querySelector('#messages').innerText"), True)
    starts_after_start = b.js("__fake.starts")

    # primeira pergunta
    assert listening(b)
    b.js("__fake.hear('O que é robótica?')")
    R.check("processando a pergunta", b.wait_state("Processando", 5) or b.wait_state("Falando", 5), True)
    R.check("resposta falada (síntese chamada com o texto da resposta)",
            b.wait_for("__fake.spoken.length === 1", 10) and "Robótica" in b.js("__fake.spoken[0]"), True)
    R.check("estado: robô falando", b.wait_state("Falando", 5), True)
    R.check("reconhecimento pausado enquanto o robô fala", b.js("__fake.running"), False)
    R.check("somente o texto reconhecido foi enviado ao processamento", b.js("__fake.chats"), ["O que é robótica?"])
    R.check("legendas: fala do visitante e resposta",
            b.js("document.querySelectorAll('#messages .user-message').length") == 1
            and b.js("document.querySelectorAll('#messages .bot-message').length") == 2, True)
    first_reply = b.js("__fake.spoken[0]")

    # a síntese termina -> volta a ouvir sozinho
    b.js("__fake.finishSpeech()")
    R.check("retomada automática da escuta após a fala", listening(b), True)
    R.check("a retomada não exigiu novo clique", b.js("__fake.clicks"), 1)
    R.check("nova captura iniciada", b.js("__fake.starts") > starts_after_start, True)

    # a própria voz do robô captada pelo microfone é ignorada
    chats_before = len(b.js("__fake.chats"))
    b.js(f"__fake.hear({json.dumps(first_reply)})")
    time.sleep(0.6)
    R.check("voz do próprio robô não é reconhecida como pergunta", len(b.js("__fake.chats")), chats_before)
    R.check("segue ouvindo depois do eco descartado", listening(b), True)

    # segunda pergunta sem clicar novamente
    ask(b, "Quem é você?")
    R.check("segunda pergunta sem novo clique", (b.js("__fake.chats")[-1], b.js("__fake.clicks")), ("Quem é você?", 1))

    # várias perguntas consecutivas
    for text in ("Bom dia", "O que é o Senac?", "Conte uma piada", "Obrigado"):
        ask(b, text)
    R.check("várias perguntas consecutivas", b.js("__fake.chats"),
            ["O que é robótica?", "Quem é você?", "Bom dia", "O que é o Senac?", "Conte uma piada", "Obrigado"])
    R.check("uma resposta falada por pergunta", b.js("__fake.spoken.length"), 6)
    R.check("ainda sem nenhum novo clique", b.js("__fake.clicks"), 1)

    # mesma frase processada duas vezes (resultado duplicado)
    assert listening(b)
    chats_before = len(b.js("__fake.chats"))
    b.js("__fake.hear('Boa tarde', true)")
    b.wait_for("__fake.ttsCurrent !== null", 10)
    b.js("__fake.finishSpeech()")
    R.check("resultado duplicado é processado uma única vez", len(b.js("__fake.chats")) - chats_before, 1)
    assert listening(b)
    b.js("__fake.hear('Boa tarde')")  # mesma frase logo em seguida
    time.sleep(0.6)
    R.check("mesma frase repetida em seguida não é processada de novo", len(b.js("__fake.chats")) - chats_before, 1)
    assert listening(b)

    # fim inesperado do reconhecimento / silêncio
    starts = b.js("__fake.starts")
    b.js("__fake.quietEnd()")
    R.check("fim inesperado do reconhecimento: reinicia sozinho", b.wait_for(f"__fake.starts > {starts} && __fake.running", 5), True)
    for _ in range(3):
        assert listening(b)
        b.js("__fake.silence()")
        time.sleep(0.3)
    R.check("silêncio repetido: segue ouvindo e orienta o visitante", listening(b) and "Pode falar" in b.state_label(), True)

    # reconhecimento sem resultado -> erro leve e volta a ouvir
    assert listening(b)
    b.js("__fake.noResult()")
    R.check("falha no reconhecimento: estado de erro com mensagem clara",
            b.wait_state("Erro", 5) and "Pode repetir" in b.state_label(), True)
    R.check("erro leve: volta a ouvir sozinho", listening(b), True)

    # perda de conexão do reconhecimento -> erro leve e retenta
    b.js("__fake.fail('network')")
    R.check("perda de conexão: mensagem clara", b.wait_state("Erro", 5) and "conexão" in b.state_label(), True)
    R.check("perda de conexão: tenta de novo", listening(b, 15), True)

    # interrupção da fala
    ask(b, "O que é inteligência artificial?", finish=False)
    R.check("botão Interromper fala aparece enquanto o robô fala", b.js("!document.querySelector('#stop-speech').hidden"), True)
    cancels = b.js("__fake.cancels")
    b.click("#stop-speech")
    R.check("interromper cancela a fala", (b.js("__fake.ttsCurrent === null"), b.js("__fake.cancels") > cancels), (True, True))
    R.check("depois de interromper volta a ouvir", listening(b), True)
    R.check("botão Interromper some quando o robô não fala", b.js("document.querySelector('#stop-speech').hidden"), True)

    # encerramento
    b.click("#conversation-button")
    R.check("encerrar: estado sessão encerrada", b.wait_state("Encerrada", 5), True)
    R.check("encerrar: botão volta a INICIAR CONVERSA", b.button_label(), "INICIAR CONVERSA")
    R.check("encerrar: reconhecimento parado (microfone liberado)", b.js("__fake.running"), False)
    R.check("encerrar: nenhuma captura de microfone ficou aberta", b.js("__fake.mic.opened === __fake.mic.stopped"), True)
    R.check("encerrar: sessão fechada no servidor", b.js("__fake.sessions.at(-1)"), "stop")
    starts = b.js("__fake.starts")
    time.sleep(1.2)
    R.check("encerrar: não volta a ouvir sozinho", (b.js("__fake.starts"), b.js("__fake.running")), (starts, False))
    R.check("encerrar: mensagem de despedida", "Obrigado" in b.state_label(), True)

    # nova conversa depois de encerrar; legendas anteriores são apagadas
    b.click("#conversation-button")
    R.check("nova conversa depois de encerrar", listening(b), True)
    R.check("legendas anteriores apagadas na nova conversa", b.js("document.querySelectorAll('#messages .message').length"), 1)

    # encerrar enquanto o robô fala: não retoma a escuta
    ask(b, "Tchau", finish=False)
    b.click("#conversation-button")
    R.check("encerrar durante a fala: fala cancelada",
            (b.wait_state("Encerrada", 5), b.js("__fake.ttsCurrent === null")), (True, True))
    starts = b.js("__fake.starts")
    time.sleep(1.0)
    R.check("encerrar durante a fala: escuta não retorna", (b.js("__fake.starts"), b.js("__fake.running")), (starts, False))

    # parada de emergência encerra a conversa e bloqueia novas
    b.click("#conversation-button")
    assert listening(b)
    api("/api/emergency")
    R.check("emergência encerra a conversa", b.wait_state("Encerrada", 8), True)
    R.check("emergência: microfone liberado", (b.js("__fake.running"), b.js("__fake.mic.opened === __fake.mic.stopped")), (False, True))
    b.click("#conversation-button")
    R.check("durante a emergência a conversa não inicia", b.wait_state("Indisponivel", 8), True)
    R.check("mensagem orienta chamar a equipe", "equipe" in b.state_label(), True)
    api("/api/emergency")

    # sair da tela do visitante encerra a conversa
    b.click("#conversation-button")
    assert listening(b)
    b.view("operator")
    R.check("trocar de tela encerra a conversa e libera o microfone",
            b.wait_for("__fake.running === false", 5) and b.js("__fake.mic.opened === __fake.mic.stopped"), True)

    R.check("sem erros de JavaScript", b.real_errors(), [])
finally:
    b.close()

# ------------------------------------------------------------------ inatividade
b = fresh(port=9502, timings={**FAST, "idleTimeoutMs": 1500})
try:
    b.click("#conversation-button")
    assert listening(b)
    R.check("inatividade: encerra sozinho e libera o microfone",
            b.wait_state("Encerrada", 6) and b.js("__fake.running") is False, True)
    R.check("inatividade: mensagem clara", "inatividade" in b.state_label(), True)
finally:
    b.close()

# ------------------------------------------------------------------ erros definitivos durante a conversa
for code, expect, port in (("not-allowed", "bloqueado", 9503), ("audio-capture", "microfone", 9504)):
    b = fresh(port=port)
    try:
        b.click("#conversation-button")
        assert listening(b)
        b.js(f"__fake.fail({json.dumps(code)})")
        R.check(f"{code} durante a conversa: indisponível", b.wait_state("Indisponivel", 5), True)
        R.check(f"{code}: mensagem clara", expect in b.state_label(), True)
        R.check(f"{code}: botão volta a INICIAR e microfone liberado", (b.button_label(), b.js("__fake.running")), ("INICIAR CONVERSA", False))
    finally:
        b.close()

# queda persistente de conexão do reconhecimento
b = fresh(port=9505)
try:
    b.click("#conversation-button")
    for _ in range(4):
        assert listening(b, 15)
        b.js("__fake.fail('network')")
        time.sleep(0.2)
    R.check("conexão perdida várias vezes: voz indisponível", b.wait_state("Indisponivel", 8), True)
    R.check("conexão perdida: mensagem fala em falta de conexão", "conexão" in b.state_label(), True)
finally:
    b.close()

# ------------------------------------------------------------------ início impossível
cases = [
    ("permissão negada", {"permission": "denied"}, "bloqueado", 9506),
    ("microfone não encontrado (permissão)", {"permission": "no-device"}, "Não encontrei um microfone", 9507),
    ("nenhum dispositivo de entrada", {"devices": 0}, "Não encontrei um microfone", 9508),
    ("microfone ocupado", {"permission": "busy"}, "outro programa", 9509),
    ("sem reconhecimento de voz no navegador", {"recognition": False}, "não está disponível neste navegador", 9510),
    ("sem API de microfone", {"getUserMedia": False}, "temporariamente indisponível", 9511),
]
for name, options, expected, port in cases:
    b = fresh(port=port, options=options)
    try:
        b.click("#conversation-button")
        R.check(f"{name}: estado microfone indisponível", b.wait_state("Indisponivel", 8), True)
        R.check(f"{name}: mensagem clara ao visitante", expected in b.state_label(), True)
        R.check(f"{name}: sem campo de texto como alternativa na tela do visitante",
                b.js("document.querySelectorAll('#visitor input, #visitor textarea').length"), 0)
        R.check(f"{name}: botão permite tentar de novo", (b.button_label(), b.js("document.querySelector('#conversation-button').disabled")),
                ("INICIAR CONVERSA", False))
        R.check(f"{name}: sessão não foi aberta e microfone não ficou aberto",
                (b.js("__fake.sessions.length"), b.js("__fake.mic.opened === __fake.mic.stopped")), (0, True))
        if name.startswith("sem reconhecimento"):
            b.view("operator")
            b.js("(()=>{const i=document.querySelector('#op-test-message');i.value='O que é robótica?';document.querySelector('#op-test-form').requestSubmit();})()")
            R.check("operador mantém teste de mensagem fora da tela do visitante",
                    b.wait_for("document.querySelector('#op-test-reply').textContent.includes('Robótica')", 8), True)
        R.check(f"{name}: sem erros de JavaScript", b.real_errors(), [])
    finally:
        b.close()

# ------------------------------------------------------------------ sem síntese de voz: legendas e escuta continuam
b = fresh(port=9512, options={"tts": False})
try:
    b.click("#conversation-button")
    assert listening(b)
    b.js("__fake.hear('Tchau')")
    R.check("sem voz sintetizada: resposta aparece nas legendas",
            b.wait_for("document.querySelectorAll('#messages .bot-message').length === 2", 8), True)
    R.check("sem voz sintetizada: a escuta retorna depois do tempo de leitura", listening(b, 15), True)
    R.check("sem voz sintetizada: sem erros de JavaScript", b.real_errors(), [])
finally:
    b.close()

sys.exit(R.summary())
