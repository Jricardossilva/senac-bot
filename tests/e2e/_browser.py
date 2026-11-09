r"""Utilitários dos testes de interface no Edge headless (DevTools Protocol) com dublês de voz.

O Edge headless não tem microfone nem alto-falante. Por isso os testes injetam, antes da página carregar,
dublês de SpeechRecognition, speechSynthesis e do microfone (veja FAKES_JS), controlados por window.__fake:

    __fake.hear("texto")      o visitante fala (resultado do reconhecimento)
    __fake.silence()          nada foi dito (no-speech)           __fake.fail("network")  erro do reconhecimento
    __fake.noResult()         houve voz, mas sem texto            __fake.quietEnd()       fim inesperado, sem erro
    __fake.finishSpeech()     a síntese terminou de falar         __fake.running          reconhecimento ativo?
    __fake.spoken / chats / sessions / mic        o que foi falado, enviado ao /chat, chamadas de sessão, uso do microfone
"""
import json
import subprocess
import sys
import tempfile
import time
import urllib.request

from websockets.sync.client import connect

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

FAKES_JS = r"""
(() => {
  const opt = Object.assign({ permission: "granted", devices: 1, recognition: true, tts: true, getUserMedia: true }, window.__FAKE_OPTIONS__ || {});
  const F = (window.__fake = { running: false, starts: 0, mic: { opened: 0, stopped: 0 }, spoken: [], chats: [], sessions: [], clicks: 0, ttsCurrent: null, cancels: 0, instance: null });
  if (window.__FAKE_TIMINGS__) window.__SENAC_VOICE_TIMINGS__ = window.__FAKE_TIMINGS__;

  if (opt.recognition) {
    class FakeRecognition extends EventTarget {
      start() {
        if (F.running) throw new DOMException("already started", "InvalidStateError");
        F.running = true; F.starts += 1; F.instance = this;
        setTimeout(() => { this.dispatchEvent(new Event("start")); this.dispatchEvent(new Event("audiostart")); }, 5);
      }
      stop() { this._end(); }
      abort() {
        if (!F.running) return;
        const e = new Event("error"); e.error = "aborted"; this.dispatchEvent(e); this._end();
      }
      _end() { if (!F.running) return; F.running = false; setTimeout(() => this.dispatchEvent(new Event("end")), 0); }
    }
    window.SpeechRecognition = FakeRecognition;
    window.webkitSpeechRecognition = FakeRecognition;
    F.hear = (text, twice = false) => {
      if (!F.running) return false;
      const r = F.instance;
      r.dispatchEvent(new Event("soundstart")); r.dispatchEvent(new Event("speechstart"));
      const ev = new Event("result"); ev.results = [[{ transcript: text, confidence: 0.9 }]];
      r.dispatchEvent(ev); if (twice) r.dispatchEvent(ev);
      // Não termina sozinho: no modo contínuo (ver speech.js), o motor de reconhecimento continua depois
      // de um resultado — é o próprio SpeechInput que decide o fim, pelo silêncio, e chama stop()/abort().
      return true;
    };
    F.silence = () => { if (!F.running) return false; const e = new Event("error"); e.error = "no-speech"; F.instance.dispatchEvent(e); F.instance._end(); return true; };
    F.fail = (code) => { if (!F.running) return false; const e = new Event("error"); e.error = code; F.instance.dispatchEvent(e); F.instance._end(); return true; };
    F.noResult = () => { if (!F.running) return false; F.instance.dispatchEvent(new Event("soundstart")); F.instance.dispatchEvent(new Event("speechstart")); F.instance._end(); return true; };
    F.quietEnd = () => { if (!F.running) return false; F.instance._end(); return true; };
  } else {
    delete window.SpeechRecognition; delete window.webkitSpeechRecognition;
  }

  if (opt.tts) {
    const synth = {
      speak(u) {
        F.ttsCurrent = u; F.spoken.push(u.text);
        setTimeout(() => u.onstart && u.onstart({}), 5);
        if (opt.autoFinish) setTimeout(() => { if (F.ttsCurrent === u) { F.ttsCurrent = null; u.onend && u.onend({}); } }, opt.autoFinish);
      },
      cancel() { F.ttsCurrent = null; F.cancels += 1; },
      getVoices() { return []; },
      addEventListener() {}
    };
    Object.defineProperty(window, "speechSynthesis", { value: synth, configurable: true });
    F.finishSpeech = () => { const u = F.ttsCurrent; F.ttsCurrent = null; if (u && u.onend) u.onend({}); return Boolean(u); };
  } else {
    Object.defineProperty(window, "speechSynthesis", { value: undefined, configurable: true });
  }

  const md = navigator.mediaDevices;
  if (md) {
    md.enumerateDevices = async () => Array.from({ length: opt.devices }, () => ({ kind: "audioinput", label: "Microfone de teste" }));
    md.getUserMedia = opt.getUserMedia ? async () => {
      if (opt.permission === "denied") throw new DOMException("negado", "NotAllowedError");
      if (opt.permission === "no-device") throw new DOMException("nenhum", "NotFoundError");
      if (opt.permission === "busy") throw new DOMException("ocupado", "NotReadableError");
      F.mic.opened += 1;
      return { getTracks: () => [{ stop() { F.mic.stopped += 1; } }] };
    } : undefined;
  }

  const realFetch = window.fetch.bind(window);
  window.fetch = (url, init) => {
    const u = String(url);
    if (u.includes("/chat") && init && init.body) F.chats.push(JSON.parse(init.body).message);
    if (u.includes("/api/session/")) F.sessions.push(u.split("/").pop());
    return realFetch(url, init);
  };
  document.addEventListener("click", (e) => { if (e.target.closest && e.target.closest("#conversation-button")) F.clicks += 1; }, true);
})();
"""


class Reporter:
    def __init__(self) -> None:
        self.results: list[bool] = []

    def check(self, name, got, want) -> bool:
        ok = got == want
        self.results.append(ok)
        print(("OK   " if ok else "FALHA"), name, "" if ok else f"-> obtido {got!r}, esperado {want!r}")
        return ok

    def summary(self) -> int:
        print(f"\n{sum(self.results)}/{len(self.results)} verificações OK")
        return 0 if all(self.results) else 1


# Tempos rápidos para a detecção de fim de fala (ver SPEECH_INPUT_DEFAULTS em speech.js): os testes com
# dublê de voz não precisam esperar os 1,5 s / 3 s reais a cada "fala" simulada. Bem abaixo do atraso fixo
# de reinício interno do motor (120 ms, ver #onEngineEnd em speech.js) para nunca entrar em disputa com ele.
FAST_SPEECH_TIMINGS = {"minSilenceMs": 30, "confirmSilenceMs": 60, "extendedSilenceMs": 90, "maxSeconds": 8}


class Browser:
    """Uma instância do Edge headless controlada por DevTools, com dublês de voz opcionais."""

    def __init__(self, base: str, port: int, fakes: bool = True, options: dict | None = None,
                 timings: dict | None = None, speech_timings: dict | None = None,
                 width: int = 1366, height: int = 900) -> None:
        self.base = base
        self.port = port
        self.errors: list[str] = []
        self._seq = 0
        self.proc = subprocess.Popen(
            [EDGE, "--headless=new", "--disable-gpu", f"--remote-debugging-port={port}",
             f"--user-data-dir={tempfile.mkdtemp()}", f"--window-size={width},{height}", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        page = None
        for _ in range(60):
            try:
                page = next(p for p in json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list")) if p["type"] == "page")
                break
            except Exception:
                time.sleep(0.5)
        if page is None:
            raise RuntimeError("Edge não iniciou")
        self.ws = connect(page["webSocketDebuggerUrl"], max_size=None, ping_interval=None)
        self.send("Runtime.enable")
        self.send("Page.enable")
        if fakes:
            script = ""
            if options:
                script += f"window.__FAKE_OPTIONS__ = {json.dumps(options)};"
            # reflectionChance: 0 por padrão nos testes — sem isso, as expressões de reflexão (aleatórias) somariam
            # falas extras a __fake.spoken e quebrariam as contagens exatas dos testes existentes. Um teste que
            # queira cobrir as expressões de reflexão pode passar timings={"reflectionChance": 1, ...}.
            effective_timings = {"reflectionChance": 0, **(timings or {})}
            script += f"window.__FAKE_TIMINGS__ = {json.dumps(effective_timings)};"
            st = FAST_SPEECH_TIMINGS if speech_timings is None else speech_timings
            if st:
                script += f"window.__SENAC_SPEECH_TIMINGS__ = {json.dumps(st)};"
            self.send("Page.addScriptToEvaluateOnNewDocument", source=script + FAKES_JS)
        self.send("Page.navigate", url=base)
        self.wait_for("document.querySelector('#connection-label')?.textContent === 'Sistema conectado'", 30)

    def send(self, method: str, **params):
        self._seq += 1
        self.ws.send(json.dumps({"id": self._seq, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("method") == "Runtime.exceptionThrown":
                self.errors.append(msg["params"]["exceptionDetails"].get("exception", {}).get("description", "exceção"))
            if msg.get("id") == self._seq:
                return msg.get("result", {})

    def js(self, expr: str):
        r = self.send("Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True)
        return "EXC" if "exceptionDetails" in r else r["result"].get("value")

    def wait_for(self, expr: str, timeout: float = 10, step: float = 0.1) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            if self.js(expr):
                return True
            time.sleep(step)
        return False

    def state(self) -> str:
        return self.js("document.querySelector('#visitor-state').dataset.state")

    def state_label(self) -> str:
        return self.js("document.querySelector('#visitor-state-label').textContent")

    def button_label(self) -> str:
        return self.js("document.querySelector('#conversation-button .conversation-label').textContent")

    def wait_state(self, state: str, timeout: float = 10) -> bool:
        return self.wait_for(f"document.querySelector('#visitor-state').dataset.state === {json.dumps(state)}", timeout)

    def click(self, selector: str):
        self.js(f"document.querySelector({json.dumps(selector)}).click()")

    def view(self, name: str):
        self.click(f".nav-button[data-view={name}]")

    def real_errors(self) -> list[str]:
        ignorable = ("favicon", "fonts.g", "ERR_INTERNET", "ERR_NAME", "Failed to load resource")
        return [e for e in self.errors if not any(i in e for i in ignorable)]

    def close(self) -> None:
        """Encerra o navegador de verdade: o processo lançador pode sair antes, então mata-se por porta de depuração."""
        try:
            self.ws.close()
        except Exception:  # noqa: BLE001
            pass
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.proc.pid)], capture_output=True)
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'remote-debugging-port=" + str(self.port) + "' } "
             "| ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"],
            capture_output=True,
        )


def base_url() -> str:
    if len(sys.argv) < 2:
        raise SystemExit("Uso: python tests\\e2e\\<script>.py http://127.0.0.1:8000/")
    return sys.argv[1]
