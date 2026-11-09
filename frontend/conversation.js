// Máquina de estados da conversa por voz. Não conhece o DOM: recebe tudo por injeção (reconhecedor,
// síntese, pedido ao robô, abertura/fechamento da sessão) e avisa a interface por callbacks.
//
// Fluxo: idle -> requesting -> listening -> processing -> speaking -> listening -> ... -> ended
// Regras de áudio:
//  - o reconhecimento só roda no estado "listening": nunca durante a fala do robô;
//  - resultados que chegam fora de "listening", repetidos ou parecidos com a fala do robô são descartados;
//  - nenhum áudio é gravado; ao encerrar, o reconhecimento é abortado e a fala cancelada.

export const STATES = Object.freeze({
  IDLE: "idle",
  REQUESTING: "requesting",
  LISTENING: "listening",
  PROCESSING: "processing",
  SPEAKING: "speaking",
  ERROR: "error",
  UNAVAILABLE: "unavailable",
  ENDED: "ended"
});

const DEFAULT_TIMINGS = Object.freeze({
  resumeDelayMs: 500, // pausa depois da fala do robô, para não captar o "rabo" do próprio som
  restartDelayMs: 250, // intervalo entre uma captura e a seguinte
  errorPauseMs: 2200, // tempo mostrando o erro antes de voltar a ouvir
  idleTimeoutMs: 120000, // sem nenhuma fala do visitante: encerra e libera o microfone
  duplicateWindowMs: 3000,
  echoWindowMs: 8000,
  silenceHintAfter: 3, // capturas silenciosas seguidas antes de lembrar o visitante de falar
  maxNetworkFailures: 3,
  maxRestartsPerWindow: 12,
  restartWindowMs: 15000,
  reflectionChance: 0.5 // chance de usar uma expressão natural de reflexão antes de respostas que exigem raciocínio
});

// Expressões curtas e variadas, só para perguntas que de fato exigem buscar/elaborar uma resposta
// (nunca em saudações ou perguntas muito simples, nunca repetidas em sequência).
const REFLECTION_PHRASES = Object.freeze([
  "Hum... deixa eu pensar um pouquinho.",
  "Boa pergunta! Deixa eu organizar essa informação.",
  "Vamos ver... já vou te explicar.",
  "Interessante! Deixa eu conferir isso.",
  "Certo, deixa eu pensar em como explicar melhor."
]);
const GREETING_OR_SIMPLE = /^(oi|ola|opa|eai|e ai|bom dia|boa tarde|boa noite|tudo bem|tchau|ate logo|ate mais|obrigad[oa]|valeu|sim|nao|entendi|certo|ok)\b/;

export function normalizeText(text) {
  return String(text)
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

// O reconhecedor ouviu a própria voz do robô? (mesma frase ou quase todas as palavras já faladas por ele)
export function isEcho(heard, robotReply) {
  if (!heard || !robotReply) return false;
  const h = normalizeText(heard);
  const r = normalizeText(robotReply);
  const words = h.split(" ").filter(Boolean);
  if (words.length < 3) return false;
  if (r.includes(h)) return true;
  const replyWords = new Set(r.split(" "));
  const shared = words.filter((word) => replyWords.has(word)).length;
  return words.length >= 4 && shared / words.length >= 0.85;
}

const readingMs = (text) => text.split(/\s+/).length * 380 + 800;
const wait = (ms) => new Promise((resolve) => window.setTimeout(resolve, ms));

export class VoiceConversation {
  #deps;
  #timings;
  #recognizer = null;
  #state = STATES.IDLE;
  #active = false;
  #session = 0;
  #turn = 0;
  #manageSession = true;
  #recognizerRunning = false;
  #lastError = null;
  #lastHeard = { text: "", at: 0 };
  #lastReply = "";
  #speechEndedAt = 0;
  #silentTurns = 0;
  #networkFailures = 0;
  #noAudioCount = 0;
  #restarts = [];
  #resumeTimer = null;
  #idleTimer = null;
  #awaitingEnd = false;
  #lastPartial = "";
  #lastFillerIndex = -1;

  // deps: { createRecognizer(handlers), speech, detectMicrophones(), requestMicrophone(), ask(text),
  //         openSession?(), closeSession?(), onState(state, detail), onCaption(role, text, meta) }
  constructor(deps, timings = {}) {
    this.#deps = deps;
    this.#timings = { ...DEFAULT_TIMINGS, ...timings };
  }

  get state() {
    return this.#state;
  }

  get active() {
    return this.#active;
  }

  // Processando ou falando: o visitante está no meio de uma troca (não dar por encerrada a janela de perguntas).
  get busy() {
    return this.#active && [STATES.PROCESSING, STATES.SPEAKING].includes(this.#state);
  }

  #set(state, detail = {}) {
    this.#state = state;
    this.#deps.onState?.(state, detail);
  }

  async start({ manageSession = true } = {}) {
    if (this.#active || this.#state === STATES.REQUESTING) return false;
    const session = ++this.#session;
    const stale = () => this.#session !== session;
    this.#manageSession = manageSession;
    this.#set(STATES.REQUESTING, { manageSession });

    if (!this.#recognizer) this.#recognizer = this.#deps.createRecognizer(this.#handlers());
    if (!this.#recognizer.supported) return this.#fail("api");

    const devices = await this.#deps.detectMicrophones();
    if (stale()) return false;
    if (devices.supported && devices.count === 0) return this.#fail("no-device");

    const permission = await this.#deps.requestMicrophone();
    if (stale()) return false;
    if (permission !== "granted") {
      const kind = { denied: "denied", "no-device": "no-device", busy: "busy" }[permission] || "error";
      return this.#fail(kind);
    }

    if (manageSession && this.#deps.openSession) {
      try {
        await this.#deps.openSession();
      } catch (error) {
        return stale() ? false : this.#fail("session", { message: error && error.message });
      }
      if (stale()) return false;
    }

    this.#active = true;
    this.#turn = 0;
    this.#silentTurns = 0;
    this.#networkFailures = 0;
    this.#noAudioCount = 0;
    this.#restarts = [];
    this.#lastError = null;
    this.#lastReply = "";
    this.#lastHeard = { text: "", at: 0 };
    this.#awaitingEnd = false;
    this.#lastPartial = "";
    this.#armIdleTimer();
    this.#listen(0);
    return true;
  }

  // Encerra a conversa a qualquer momento e libera o microfone. reason: user | idle | emergency | operator | view | demo
  async stop(reason = "user") {
    const wasActive = this.#active;
    this.#session += 1; // invalida qualquer operação em andamento
    this.#active = false;
    this.#clearTimers();
    this.#recognizerRunning = false;
    if (this.#recognizer) this.#recognizer.abort();
    this.#deps.speech.cancel();
    if (wasActive || this.#state === STATES.REQUESTING) {
      this.#set(STATES.ENDED, { reason });
      if (wasActive && this.#manageSession && this.#deps.closeSession && !["emergency", "operator"].includes(reason)) {
        try {
          await this.#deps.closeSession();
        } catch {
          // a sessão do servidor é corrigida pela próxima atualização de estado
        }
      }
    }
  }

  // Interrupção explícita da fala do robô (resposta ou expressão de reflexão): a escuta recomeça sozinha.
  interrupt() {
    if (this.#active && this.#deps.speech.speaking) this.#deps.speech.cancel();
  }

  #clearTimers() {
    window.clearTimeout(this.#resumeTimer);
    window.clearTimeout(this.#idleTimer);
  }

  #armIdleTimer() {
    window.clearTimeout(this.#idleTimer);
    this.#idleTimer = window.setTimeout(() => this.stop("idle"), this.#timings.idleTimeoutMs);
  }

  #fail(kind, extra = {}) {
    this.#active = false;
    this.#clearTimers();
    this.#set(STATES.UNAVAILABLE, { kind, ...extra });
    return false;
  }

  #fatalWhileActive(kind) {
    // Perda definitiva durante a conversa: libera tudo e informa que a voz ficou indisponível.
    this.#session += 1;
    this.#active = false;
    this.#clearTimers();
    this.#recognizerRunning = false;
    this.#recognizer.abort();
    this.#deps.speech.cancel();
    this.#set(STATES.UNAVAILABLE, { kind });
    if (this.#manageSession && this.#deps.closeSession) {
      Promise.resolve(this.#deps.closeSession()).catch(() => {});
    }
  }

  // Inicia uma captura (uma por vez). delay evita captar o fim da fala do robô e colisões do navegador.
  #listen(delay = this.#timings.restartDelayMs) {
    window.clearTimeout(this.#resumeTimer);
    const session = this.#session;
    this.#resumeTimer = window.setTimeout(() => {
      if (!this.#active || this.#session !== session) return;
      if (this.#deps.speech.speaking || this.#recognizerRunning) {
        this.#listen(this.#timings.restartDelayMs); // nunca ouvir durante a fala nem sobrepor capturas
        return;
      }
      const now = Date.now();
      this.#restarts = this.#restarts.filter((t) => now - t < this.#timings.restartWindowMs);
      if (this.#restarts.push(now) > this.#timings.maxRestartsPerWindow) {
        this.#fatalWhileActive("error"); // laço de reinícios: algo está errado com o reconhecimento
        return;
      }
      this.#lastError = null;
      this.#awaitingEnd = false;
      this.#lastPartial = "";
      this.#set(STATES.LISTENING);
      if (!this.#recognizer.start()) this.#listen(this.#timings.restartDelayMs);
    }, delay);
  }

  #handlers() {
    return {
      onStart: () => {
        this.#recognizerRunning = true;
      },
      onResult: (text) => this.#onResult(text),
      onError: (code) => {
        this.#lastError = code;
      },
      onEnd: () => this.#onEnd(),
      // Acompanhamento ao vivo da escuta (só para diagnóstico do operador; nunca aparece para o visitante).
      onPartial: (text) => {
        this.#lastPartial = text;
        this.#deps.onListening?.({ partial: text, awaitingEnd: this.#awaitingEnd });
      },
      // Silêncio detectado (>= pausa mínima) sem ainda confirmar o fim: o visitante pode estar pensando ou
      // fazendo uma pausa para respirar. Mantém o estado "ouvindo", só com um sinal visual mais atencioso.
      onAwaitingEnd: (flag) => {
        this.#awaitingEnd = flag;
        if (this.#active && this.#state === STATES.LISTENING) this.#set(STATES.LISTENING, { awaitingEnd: flag });
        this.#deps.onListening?.({ partial: this.#lastPartial, awaitingEnd: flag });
      }
    };
  }

  #onResult(text) {
    if (!this.#active || this.#state !== STATES.LISTENING) return; // fora da escuta: descarta
    const now = Date.now();
    const normalized = normalizeText(text);
    if (!normalized) return;
    if (this.#speechEndedAt && now - this.#speechEndedAt < this.#timings.echoWindowMs && isEcho(text, this.#lastReply)) {
      return; // era a voz do próprio robô
    }
    if (normalized === this.#lastHeard.text && now - this.#lastHeard.at < this.#timings.duplicateWindowMs) {
      return; // mesma frase processada há instantes
    }
    this.#lastHeard = { text: normalized, at: now };
    this.#silentTurns = 0;
    this.#networkFailures = 0;
    this.#noAudioCount = 0;
    this.#restarts = []; // houve fala aceita: o reconhecimento está saudável
    this.#armIdleTimer();
    this.#process(text);
  }

  #onEnd() {
    this.#recognizerRunning = false;
    if (!this.#active) return;
    if (this.#state !== STATES.LISTENING) return; // resultado aceito: retoma depois da resposta
    const code = this.#lastError;
    this.#lastError = null;
    switch (code) {
      case "not-allowed":
      case "service-not-allowed":
        return this.#fatalWhileActive("denied");
      case "audio-capture":
        return this.#fatalWhileActive("no-device");
      case "language-not-supported":
        return this.#fatalWhileActive("api");
      case "no-audio":
        // O navegador não conseguiu abrir o microfone: tenta de novo e, persistindo, dá como indisponível.
        this.#noAudioCount += 1;
        if (this.#noAudioCount >= 3) return this.#fatalWhileActive("no-device");
        return this.#softError("no-audio", this.#timings.errorPauseMs);
      case "network":
        this.#networkFailures += 1;
        if (this.#networkFailures > this.#timings.maxNetworkFailures) return this.#fatalWhileActive("network");
        return this.#softError("network", this.#timings.errorPauseMs * 2);
      case "no-result":
        return this.#softError("no-result", this.#timings.errorPauseMs);
      case "aborted":
        return this.#listen();
      default: {
        // Silêncio (no-speech/no-sound ou fim sem erro) é normal num stand: volta a ouvir sem barulho.
        this.#silentTurns += 1;
        const hint = this.#silentTurns === this.#timings.silenceHintAfter;
        this.#set(STATES.LISTENING, { silent: true, hint });
        return this.#listen();
      }
    }
  }

  #softError(kind, pauseMs) {
    this.#set(STATES.ERROR, { kind });
    this.#listen(pauseMs);
  }

  // Pergunta simples/saudação ou nenhum sinal de que vale a pena "pensar alto"? Não usa expressão de reflexão.
  #shouldReflect(text) {
    const normalized = normalizeText(text);
    const words = normalized.split(" ").filter(Boolean);
    if (words.length < 4) return false; // saudações e perguntas muito curtas
    if (GREETING_OR_SIMPLE.test(normalized)) return false;
    return Math.random() < this.#timings.reflectionChance; // não em toda resposta
  }

  #pickFiller() {
    let index = Math.floor(Math.random() * REFLECTION_PHRASES.length);
    if (REFLECTION_PHRASES.length > 1 && index === this.#lastFillerIndex) {
      index = (index + 1) % REFLECTION_PHRASES.length;
    }
    this.#lastFillerIndex = index;
    return REFLECTION_PHRASES[index];
  }

  async #process(text) {
    const session = this.#session;
    const turn = ++this.#turn;
    const stale = () => this.#session !== session || this.#turn !== turn || !this.#active;
    this.#set(STATES.PROCESSING);
    this.#deps.onCaption?.("user", text);
    if (this.#recognizerRunning) this.#recognizer.abort();

    // A expressão de reflexão fala em paralelo à consulta (não atrasa o pedido ao Gemini); se a resposta
    // chegar antes dela terminar, espera-a terminar para não sobrepor os dois áudios.
    let fillerDone = null;
    if (this.#deps.speech.supported && this.#shouldReflect(text)) {
      fillerDone = new Promise((resolve) => {
        if (!this.#deps.speech.speak(this.#pickFiller(), { onEnd: resolve, onError: resolve })) resolve();
      });
    }

    let reply;
    try {
      reply = await this.#deps.ask(text);
    } catch (error) {
      if (stale()) return;
      this.#deps.speech.cancel();
      this.#set(STATES.ERROR, { kind: "ask", message: error && error.message });
      this.#listen(this.#timings.errorPauseMs);
      return;
    }
    if (stale()) return;
    this.#lastReply = reply.response;
    this.#deps.onCaption?.("robot", reply.response, { source: reply.source, links: reply.links });
    if (fillerDone) await fillerDone;
    if (stale()) return;
    await this.#speak(reply.response, session, turn);
  }

  async #speak(text, session, turn) {
    const stale = () => this.#session !== session || !this.#active;
    this.#set(STATES.SPEAKING);
    const finish = () => {
      if (stale()) return;
      this.#speechEndedAt = Date.now();
      this.#armIdleTimer();
      this.#listen(this.#timings.resumeDelayMs);
    };
    if (!this.#deps.speech.supported) {
      await wait(readingMs(text)); // sem voz: a legenda fica na tela pelo tempo de leitura
      finish();
      return;
    }
    let ended = false;
    let watchdog = null;
    const once = () => {
      if (ended) return;
      ended = true;
      window.clearTimeout(watchdog);
      finish();
    };
    // O Chrome às vezes não dispara o fim da fala: sem este vigia a conversa travaria no estado "falando".
    watchdog = window.setTimeout(() => {
      if (stale() || ended) return;
      this.#deps.speech.cancel();
      once();
    }, readingMs(text) * 2 + 5000);
    let started = false;
    try {
      started = this.#deps.speech.speak(text, { onEnd: once, onError: () => {} });
    } catch {
      started = false; // síntese com defeito: a resposta segue só pela legenda e a escuta continua
    }
    if (!started) once();
  }
}
