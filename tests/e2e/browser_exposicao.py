r"""Modo exposição e câmera de presença no Edge headless (voz simulada; câmera de teste do Edge; leituras de rosto injetadas).

Uso (servidor em execução):  .\.venv\Scripts\python.exe tests\e2e\browser_exposicao.py http://127.0.0.1:8000/
Cobre: tela só do visitante; portão INICIAR ESTAÇÃO; detector de rosto (MediaPipe, arquivos locais) carregando de verdade;
indicador de câmera ativa; início automático (saudação ANTES do microfone, sem clique); sem reinício sobre quem ficou parado;
encerramento por silêncio liberando o microfone; olhar do avatar; operador desligando a câmera; reinício e limpeza da tela.
Tempos reduzidos por ganchos de teste (permanência 0,4 s, saída 1,5 s, silêncio 3 s); as leituras de rosto são injetadas
em tempo real; as leituras da câmera de teste do Edge (um padrão colorido que o detector chega a tomar por rosto) são ignoradas."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _browser import Browser, Reporter, base_url  # noqa: E402

BASE = base_url().rstrip("/") + "/?modo=exposicao"
R = Reporter()
HOOKS = {"presence": {"dwellMs": 400, "flickerGraceMs": 500, "leaveMs": 1500}, "autoStartIdleMs": 3000, "ignoreCameraSamples": True}
b = Browser(BASE, 9310, options={"realVideo": True, "autoFinish": 0, "hooks": HOOKS}, timings={"resumeDelayMs": 100, "restartDelayMs": 60},
            extra_args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"])
NEAR = "{ ratio: 0.3, centerX: 0.2 }"
FAR = "{ ratio: 0.05, centerX: 0.5 }"


def feed(face: str, seconds: float, step: float = 0.1) -> None:
    """Injeta leituras do rosto em tempo real durante `seconds` (face: objeto JS ou 'null')."""
    end = time.time() + seconds
    while time.time() < end:
        b.js(f"window.__SENAC_TEST_HOOKS__.presenceSample({face}, performance.now())")
        time.sleep(step)


def gaze() -> float:
    return float(b.js("getComputedStyle(document.getElementById('visitor-robot')).getPropertyValue('--gaze') || '0'"))


try:
    R.check("só a tela do visitante (sem navegação)", b.js("getComputedStyle(document.querySelector('.mode-nav')).display"), "none")
    R.check("operador/simulador/diagnóstico escondidos",
            b.js("['operator','simulator','diagnostics'].every(id => getComputedStyle(document.getElementById(id)).display === 'none')"), True)
    R.check("portão de início visível", b.js("!document.getElementById('station-gate').hidden"), True)
    R.check("câmera desligada antes de iniciar", b.js("document.getElementById('camera-indicator').hidden"), True)

    b.click("#station-start")
    R.check("portão some após iniciar", b.wait_for("document.getElementById('station-gate').hidden", 5), True)
    R.check("detector de rosto carregou e a câmera ligou (indicador visível)",
            b.wait_for("!document.getElementById('camera-indicator').hidden", 60), True)
    R.check("indicador informa que nada é gravado", "Nada é gravado" in b.js("document.getElementById('camera-indicator').textContent"), True)
    R.check("microfone pedido na preparação e liberado",
            b.js("window.__fake.mic.opened >= 1 && window.__fake.mic.opened === window.__fake.mic.stopped"), True)

    R.check("tela de atração visível com a estação ligada", b.wait_for("!document.getElementById('attract-banner').hidden", 5), True)
    R.check("convite com a câmera ligada", "Vamos conversar" in b.js("document.getElementById('attract-text').textContent"), True)
    feed(FAR, 1.5)
    R.check("rosto longe: convite pede para chegar mais perto", "Aproxime-se um pouco" in b.js("document.getElementById('attract-text').textContent"), True)
    R.check("rosto longe não inicia", b.js("window.__fake.spoken.length"), 0)
    feed(NEAR, 0.05)
    feed("null", 1.5)
    R.check("quem só passa não inicia", b.js("window.__fake.spoken.length"), 0)

    feed(NEAR, 1.0)
    R.check("saudação falada sem clique", b.wait_for("window.__fake.spoken.length === 1", 5), True)
    R.check("saudação convida a conversar", "Quer conversar" in b.js("window.__fake.spoken[0]"), True)
    R.check("convite some durante a saudação", b.wait_for("document.getElementById('attract-banner').hidden", 3), True)
    R.check("microfone ainda fechado durante a saudação", b.js("window.__fake.running === false && window.__fake.starts === 0"), True)
    R.check("olhar acompanha o rosto (lado direito da tela)", gaze() > 0, True)

    b.js("window.__fake.finishSpeech()")
    R.check("microfone abre DEPOIS da saudação", b.wait_for("window.__fake.running === true", 5), True)
    R.check("estado Ouvindo", b.wait_state("Ouvindo", 5), True)

    feed(NEAR, 1.0)
    R.check("sem nova saudação durante a conversa", b.js("window.__fake.spoken.length"), 1)

    # Sem resposta: encerra pelo limite curto de teste (3 s) e libera o microfone.
    R.check("silêncio encerra a conversa e libera o microfone", b.wait_for("window.__fake.running === false", 8), True)
    R.check("conversa encerrada por inatividade", b.wait_for("document.querySelector('#visitor-state').dataset.state === 'Encerrada'", 5), True)

    feed(NEAR, 4.0)
    R.check("quem ficou parado não reinicia", (b.js("window.__fake.spoken.length"), b.js("window.__fake.running")), (1, False))

    feed("null", 2.5)
    feed(NEAR, 1.0)
    R.check("novo visitante é saudado", b.wait_for("window.__fake.spoken.length === 2", 5), True)
    b.js("window.__fake.finishSpeech()")
    R.check("microfone abre para o novo visitante", b.wait_for("window.__fake.running === true", 5), True)

    b.js("new BroadcastChannel('senac-bot-experience').postMessage({ type: 'presence', enabled: false })")
    R.check("operador desliga a câmera", b.wait_for("document.getElementById('camera-indicator').hidden", 5), True)
    R.check("olhar volta ao centro", gaze(), 0.0)

    b.js("new BroadcastChannel('senac-bot-experience').postMessage('reset-experience')")
    R.check("reinício encerra a conversa", b.wait_for("window.__fake.running === false", 5), True)
    R.check("reinício limpa as legendas", b.wait_for("document.querySelectorAll('#messages .message').length === 1", 5), True)
    R.check("estado volta a Aguardando", b.wait_state("Aguardando", 5), True)
    R.check("tela de atração volta depois do reinício", b.wait_for("!document.getElementById('attract-banner').hidden", 5), True)

    R.check("sem erros de JavaScript", b.real_errors(), [])
finally:
    b.close()
raise SystemExit(R.summary())
