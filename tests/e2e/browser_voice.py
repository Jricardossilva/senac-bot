r"""Voz masculina em português (painel do operador): seleção automática, nunca uma voz feminina, teste e velocidade.

Uso (servidor em execução):  .\.venv\Scripts\python.exe tests\e2e\browser_voice.py http://127.0.0.1:8000/
Roda no Edge REAL (sem dublê de voz: o bug corrigido aqui só aparecia com o SpeechSynthesis de verdade, por causa do
momento em que o navegador entrega a lista de vozes). Para não depender das vozes instaladas nesta máquina, cada
cenário troca `window.speechSynthesis` por uma lista de vozes sintética, injetada antes de qualquer script da página.
"""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _browser import Browser, Reporter, base_url  # noqa: E402

BASE = base_url()
R = Reporter()

# (nome da voz, idioma) — nomes iguais aos que o Windows/Edge realmente usam, para o teste ficar realista.
SCENARIOS = {
    "maleBr": [
        ("Microsoft Antônio Online (Natural) - Portuguese (Brazil)", "pt-BR"),  # masculina, natural: deve ser a escolhida
        ("Microsoft Francisca Online (Natural) - Portuguese (Brazil)", "pt-BR"),  # feminina: nunca pode ser escolhida
        ("Microsoft Daniel - Portuguese (Brazil)", "pt-BR"),  # masculina, mas não "Online (Natural)": perde para a Antônio
    ],
    "femaleOnly": [
        ("Microsoft Francisca Online (Natural) - Portuguese (Brazil)", "pt-BR"),
        ("Microsoft Maria - Portuguese (Brazil)", "pt-BR"),
        ("Microsoft Daniel - English (United Kingdom)", "en-GB"),  # masculina, mas doutro idioma: não deve ser usada (prejudica a pronúncia)
    ],
    "ptPtOnly": [
        ("Microsoft Duarte Online (Natural) - Portuguese (Portugal)", "pt-PT"),  # único macho em português: vira o alternativo
        ("Microsoft Raquel Online (Natural) - Portuguese (Portugal)", "pt-PT"),
    ],
    "none": [],  # navegador sem nenhuma voz instalada
}

STUB_JS = """(() => {
  const SCENARIOS = %s;
  const key = localStorage.getItem('__voice_scenario__') || 'maleBr';
  const list = (SCENARIOS[key] || []).map(([name, lang]) => ({ name, lang, default: false, localService: true, voiceURI: name }));
  const fakeSynth = {
    _voices: list,
    getVoices() { return this._voices; },
    addEventListener() {}, removeEventListener() {},
    speak(utt) {
      window.__spoken = { text: utt.text, lang: utt.lang, rate: utt.rate, voiceName: utt.voice ? utt.voice.name : null, voiceLang: utt.voice ? utt.voice.lang : null };
      setTimeout(() => utt.onstart && utt.onstart(), 0);
      setTimeout(() => utt.onend && utt.onend(), 15);
    },
    cancel() {},
  };
  Object.defineProperty(window, 'speechSynthesis', { value: fakeSynth, configurable: true });
  window.SpeechSynthesisUtterance = function (text) {
    this.text = text; this.lang = ''; this.rate = 1; this.volume = 1; this.voice = null;
    this.onstart = null; this.onend = null; this.onerror = null;
  };
})();""" % json.dumps(SCENARIOS, ensure_ascii=False)

FEMALE_NAME_FRAGMENTS = ("francisca", "maria", "luciana", "camila")


def load_scenario(b: Browser, key: str) -> None:
    b.js(f"localStorage.setItem('__voice_scenario__', {json.dumps(key)}); window.__spoken = null;")
    b.send("Page.navigate", url=BASE)
    b.wait_for("document.querySelector('#voice-summary')?.dataset.ready !== undefined", 10)


b = Browser(BASE, 9515, fakes=False, width=1200, height=900)  # Edge real: precisamos do SpeechSynthesis de verdade
try:
    b.send("Page.addScriptToEvaluateOnNewDocument", source=STUB_JS)
    b.click("[data-view=operator]")

    # ---------------------------------------------------------------- cenário 1: voz masculina natural em pt-BR disponível
    load_scenario(b, "maleBr")
    summary = b.js("document.querySelector('#voice-summary').textContent")
    R.check("voz masculina natural em pt-BR é escolhida (Antônio, não Daniel)", "Antônio" in summary and "Daniel" not in summary, True)
    R.check("nunca escolhe a voz feminina (Francisca)", any(f in summary.lower() for f in FEMALE_NAME_FRAGMENTS), False)
    R.check("estado do card: pronto (verde)", b.js("document.querySelector('#voice-summary').dataset.ready"), "true")
    b.click("#voice-test")
    b.wait_for("window.__spoken !== null", 5)
    spoken = b.js("window.__spoken")
    R.check("o teste de voz realmente fala com a voz masculina escolhida", spoken["voiceName"], "Microsoft Antônio Online (Natural) - Portuguese (Brazil)")
    R.check("a fala de teste é em pt-BR", spoken["lang"], "pt-BR")

    # ---------------------------------------------------------------- controle de velocidade
    b.wait_for("document.querySelector('#voice-test').disabled === false", 5)  # espera o botão voltar do primeiro teste (onend)
    b.js("const el = document.querySelector('#voice-rate'); el.value = '1.1'; el.dispatchEvent(new Event('input', {bubbles: true}));")
    R.check("velocidade mostrada muda ao mexer no controle", b.js("document.querySelector('#voice-rate-value').textContent"), "1.10x")
    R.check("velocidade persiste (mesmo mecanismo de preferências do operador)", b.js("localStorage.getItem('senac-bot-speech-rate')"), "1.1")
    b.click("#voice-test")
    b.wait_for("window.__spoken && window.__spoken.rate === 1.1", 5)
    R.check("a nova velocidade é usada na fala seguinte", b.js("window.__spoken.rate"), 1.1)
    b.js("localStorage.removeItem('senac-bot-speech-rate')")

    # ---------------------------------------------------------------- cenário 2: só há vozes femininas (+ uma masculina em inglês)
    load_scenario(b, "femaleOnly")
    summary = b.js("document.querySelector('#voice-summary').textContent")
    R.check("sem voz masculina em português: avisa o operador", "Nenhuma voz masculina em português" in summary, True)
    R.check("estado do card: atenção", b.js("document.querySelector('#voice-summary').dataset.ready"), "false")
    R.check("cita a voz masculina de outro idioma só como informação (não seleciona)", "Daniel" in summary, True)
    R.check("nunca escolhe a voz feminina (Francisca/Maria) mesmo sem alternativa masculina em português", any(f in summary.lower() for f in FEMALE_NAME_FRAGMENTS), False)
    b.click("#voice-test")
    b.wait_for("window.__spoken !== null", 5)
    spoken = b.js("window.__spoken")
    R.check("a fala de teste não usa a voz masculina de outro idioma (preserva a pronúncia do português)", spoken["voiceName"], None)
    R.check("mesmo sem voz masculina, a conversa não é interrompida (ainda fala)", spoken["text"].startswith("Olá!"), True)

    # ---------------------------------------------------------------- cenário 3: só existe voz masculina em pt-PT (outra região)
    load_scenario(b, "ptPtOnly")
    summary = b.js("document.querySelector('#voice-summary').textContent")
    R.check("sem pt-BR, usa a masculina de outra região do português (Duarte, pt-PT)", "Duarte" in summary, True)
    R.check("avisa que não é pt-BR", "sem voz masculina em pt-BR" in summary, True)
    R.check("estado do card: pronto (ainda assim, é uma voz masculina)", b.js("document.querySelector('#voice-summary').dataset.ready"), "true")
    b.click("#voice-test")
    b.wait_for("window.__spoken !== null", 5)
    spoken = b.js("window.__spoken")
    R.check("fala de teste usa a voz masculina pt-PT", (spoken["voiceName"], spoken["voiceLang"]), ("Microsoft Duarte Online (Natural) - Portuguese (Portugal)", "pt-PT"))

    # ---------------------------------------------------------------- cenário 4: nenhuma voz instalada
    load_scenario(b, "none")
    R.check("sem nenhuma voz: também avisa (sem travar)", "Nenhuma voz masculina em português" in b.js("document.querySelector('#voice-summary').textContent"), True)
    R.check("botão de teste continua ativo (não interrompe a conversa por falta de voz)", b.js("document.querySelector('#voice-test').disabled"), False)

    # ---------------------------------------------------------------- nada quebrou no caminho (o bug original travava TODO o app.js)
    R.check("sem erros no console em nenhum cenário", b.real_errors(), [])
    R.check("o resto da interface do operador continua funcionando", b.js("document.querySelector('#run-preflight') !== null"), True)
finally:
    b.close()
sys.exit(R.summary())
