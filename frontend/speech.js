// Camada de voz independente da interface: reconhecimento (Web Speech API) e síntese (SpeechSynthesis).
// Nenhum áudio é gravado, salvo ou enviado ao backend; o navegador processa a captura.

const RECOGNITION_ERRORS = {
  "not-allowed": "Permissão do microfone negada. Libere o microfone no navegador (ícone de cadeado) e no Windows.",
  "service-not-allowed": "O navegador bloqueou o reconhecimento de voz. Verifique as permissões ou digite sua mensagem.",
  "audio-capture": "Nenhum microfone disponível. Verifique se ele está conectado e liberado no Windows, ou digite sua mensagem.",
  "no-speech": "Não ouvi nada. Aperte o botão de voz e fale de novo, ou digite sua mensagem.",
  "network": "O reconhecimento de voz do navegador precisa de internet. Digite sua mensagem.",
  "language-not-supported": "O navegador não oferece reconhecimento em português do Brasil. Digite sua mensagem.",
  "bad-grammar": "Não foi possível reconhecer a fala. Digite sua mensagem.",
  "no-audio": "O navegador não conseguiu abrir o microfone. Escolha o microfone certo em Configurações do Windows > Sistema > Som > Entrada e feche outros programas que o estejam usando.",
  "no-sound": "O microfone abriu, mas não captou nenhum som. Fale logo depois de aparecer \"Estou ouvindo\" e confira o microfone selecionado, se ele não está mudo e o volume de entrada no Windows.",
  "no-result": "Ouvi sua voz, mas o serviço de reconhecimento não devolveu o texto. Verifique a internet e a opção 'Reconhecimento de voz online' em Configurações do Windows > Privacidade e segurança > Fala."
};

export function describeSpeechError(code) {
  if (code === "aborted") return "";
  return RECOGNITION_ERRORS[code] || "Não foi possível reconhecer a fala. Tente novamente ou digite sua mensagem.";
}

export async function detectMicrophones() {
  if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) {
    return { supported: false, count: 0, labels: [] };
  }
  try {
    const devices = await navigator.mediaDevices.enumerateDevices();
    const inputs = devices.filter((device) => device.kind === "audioinput");
    return { supported: true, count: inputs.length, labels: inputs.map((d) => d.label).filter(Boolean) };
  } catch {
    return { supported: false, count: 0, labels: [] };
  }
}

export async function queryMicPermission() {
  try {
    const status = await navigator.permissions.query({ name: "microphone" });
    return status.state; // "granted" | "denied" | "prompt"
  } catch {
    return "unknown";
  }
}

// Pede ao navegador a permissão do microfone. O fluxo é aberto apenas para acionar a permissão e é fechado na hora:
// nenhum áudio é lido, gravado ou guardado. Resultado: granted | denied | no-device | busy | unsupported | error.
export async function requestMicrophoneAccess() {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return "unsupported";
  let stream = null;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    return "granted";
  } catch (error) {
    const name = error && error.name;
    if (name === "NotAllowedError" || name === "SecurityError") return "denied";
    if (name === "NotFoundError" || name === "OverconstrainedError") return "no-device";
    if (name === "NotReadableError" || name === "AbortError") return "busy";
    return "error";
  } finally {
    if (stream) stream.getTracks().forEach((track) => track.stop());
  }
}

// Códigos de erro do reconhecimento que realmente encerram a captura (falha real, não silêncio).
const FATAL_RECOGNITION_ERRORS = new Set([
  "not-allowed", "service-not-allowed", "audio-capture", "language-not-supported", "bad-grammar",
]);
// Palavras/trechos finais que sugerem frase incompleta (o visitante ainda vai continuar).
const CONTINUATION_WORDS = new Set([
  "e", "mas", "entao", "so", "ou", "porque", "tipo", "ne", "ai", "dai", "tambem", "pois", "que",
]);
const CONTINUATION_PHRASES = new Set([
  "deixa eu", "por exemplo", "quer dizer", "ou seja", "como assim", "e tambem", "so que", "alem disso", "ai eu",
]);
const MAX_SILENCE_EXTENSIONS = 2; // quantas vezes o tempo de confirmação pode ser ampliado por frase aparentemente incompleta
const MAX_INNER_RESTARTS = 40; // reinícios internos do motor de reconhecimento dentro de UMA mesma captura (ex.: silêncios longos)

export const SPEECH_INPUT_DEFAULTS = Object.freeze({
  maxSeconds: 45, // limite de segurança: evita uma sessão de escuta interminável
  minSilenceMs: 1500, // pausa mínima para começar a suspeitar que o visitante terminou
  confirmSilenceMs: 3000, // silêncio contínuo necessário para confirmar o fim da fala
  extendedSilenceMs: 4500, // tempo usado quando a frase parece incompleta (ex.: termina em "e", "mas", vírgula)
});

function stripAccents(text) {
  return String(text || "").normalize("NFD").replace(/[̀-ͯ]/g, "");
}

// A frase parece incompleta (termina em vírgula ou numa palavra/expressão de continuação)?
function looksIncomplete(text) {
  const raw = String(text || "").trim();
  if (!raw) return false;
  if (/[,;:]$/.test(raw)) return true;
  const normalized = stripAccents(raw).toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  if (!normalized) return false;
  const words = normalized.split(" ").filter(Boolean);
  const lastWord = words[words.length - 1];
  const tail2 = words.slice(-2).join(" ");
  return CONTINUATION_WORDS.has(lastWord) || CONTINUATION_PHRASES.has(tail2);
}

// Reconhecimento contínuo com detecção própria do fim da fala: não usa o corte interno do navegador
// (que trata qualquer pausa curta como fim), mas um tempo de silêncio configurável, ampliado quando a
// frase parece incompleta. Uma captura (start→onResult/onEnd) pode reiniciar o motor várias vezes por
// dentro (silêncios longos, paradas do próprio navegador) sem nunca descartar o texto já reconhecido.
export class SpeechInput {
  #Impl;
  #engine = null;
  #handlers;
  #lang;
  #maxMs;
  #minSilenceMs;
  #confirmSilenceMs;
  #extendedSilenceMs;
  #active = false;
  #listening = false;
  #finished = true;
  #transcript = "";
  #interim = "";
  #awaitingEnd = false;
  #extensions = 0;
  #restartGuard = 0;
  #deadline = 0;
  #fatalErrorCode = null;
  #networkErrorPending = false;
  #processedFinalCount = 0;
  #awaitTimer = null;
  #silenceTimer = null;
  #maxTimer = null;
  #progress = { audio: false, sound: false, speech: false, result: false, error: false, aborted: false };

  constructor(handlers = {}, options = {}) {
    this.#handlers = handlers;
    const {
      lang = "pt-BR",
      maxSeconds = SPEECH_INPUT_DEFAULTS.maxSeconds,
      minSilenceMs = SPEECH_INPUT_DEFAULTS.minSilenceMs,
      confirmSilenceMs = SPEECH_INPUT_DEFAULTS.confirmSilenceMs,
      extendedSilenceMs = SPEECH_INPUT_DEFAULTS.extendedSilenceMs,
    } = options;
    this.#lang = lang;
    this.#maxMs = maxSeconds * 1000;
    this.#minSilenceMs = minSilenceMs;
    this.#confirmSilenceMs = confirmSilenceMs;
    this.#extendedSilenceMs = extendedSilenceMs;
    this.#Impl = window.SpeechRecognition || window.webkitSpeechRecognition || null;
  }

  get supported() {
    return this.#Impl !== null;
  }

  // Captura lógica em andamento (pode ter reiniciado o motor várias vezes por dentro).
  get listening() {
    return this.#active;
  }

  start() {
    if (!this.#Impl || this.#active) return false;
    this.#active = true;
    this.#finished = false;
    this.#transcript = "";
    this.#interim = "";
    this.#awaitingEnd = false;
    this.#extensions = 0;
    this.#restartGuard = 0;
    this.#fatalErrorCode = null;
    this.#networkErrorPending = false;
    this.#processedFinalCount = 0;
    this.#progress = { audio: false, sound: false, speech: false, result: false, error: false, aborted: false };
    this.#deadline = Date.now() + this.#maxMs;
    this.#maxTimer = window.setTimeout(() => this.#confirmEnd(), this.#maxMs);
    this.#handlers.onStart?.();
    this.#startEngine();
    return true;
  }

  #startEngine() {
    const recognition = new this.#Impl();
    recognition.lang = this.#lang;
    recognition.continuous = true; // a própria API não decide mais o fim: nós decidimos, pelo silêncio
    recognition.interimResults = true; // acompanha a fala enquanto ela acontece (sem isso não há como medir o silêncio)
    recognition.maxAlternatives = 1;
    recognition.addEventListener("audiostart", () => (this.#progress.audio = true));
    recognition.addEventListener("soundstart", () => (this.#progress.sound = true));
    recognition.addEventListener("speechstart", () => (this.#progress.speech = true));
    recognition.addEventListener("result", (event) => this.#onEngineResult(event));
    recognition.addEventListener("error", (event) => this.#onEngineError(event));
    recognition.addEventListener("end", () => this.#onEngineEnd());
    this.#engine = recognition;
    try {
      recognition.start();
      this.#listening = true;
    } catch {
      this.#handlers.onError?.("audio-capture");
      this.#finishCapture();
    }
  }

  #fullText() {
    return `${this.#transcript} ${this.#interim}`.trim();
  }

  #onEngineResult(event) {
    if (this.#finished) return;
    const startIndex = Number.isFinite(event.resultIndex) ? event.resultIndex : 0;
    let finalChunk = "";
    let interimChunk = "";
    for (let i = startIndex; i < event.results.length; i += 1) {
      const result = event.results[i];
      const text = result[0]?.transcript || "";
      const isFinal = result.isFinal !== false; // a API sempre informa um booleano; nunca undefined de verdade
      if (isFinal) {
        // Um índice já incorporado ao texto não é somado de novo (ex.: o mecanismo reenvia o mesmo resultado).
        if (i >= this.#processedFinalCount) {
          finalChunk += text;
          this.#processedFinalCount = i + 1;
        }
      } else {
        interimChunk += text;
      }
    }
    if (finalChunk.trim()) this.#transcript = `${this.#transcript} ${finalChunk}`.trim();
    this.#interim = interimChunk.trim();
    if (this.#transcript || this.#interim) this.#progress.result = true;
    this.#handlers.onPartial?.(this.#fullText());
    this.#resetSilenceTimers();
  }

  #resetSilenceTimers() {
    window.clearTimeout(this.#awaitTimer);
    window.clearTimeout(this.#silenceTimer);
    if (this.#awaitingEnd) {
      this.#awaitingEnd = false;
      this.#handlers.onAwaitingEnd?.(false);
    }
    this.#awaitTimer = window.setTimeout(() => {
      this.#awaitingEnd = true;
      this.#handlers.onAwaitingEnd?.(true);
    }, this.#minSilenceMs);
    this.#armConfirmTimer(this.#confirmSilenceMs);
  }

  #armConfirmTimer(delay) {
    window.clearTimeout(this.#silenceTimer);
    const remaining = this.#deadline - Date.now();
    this.#silenceTimer = window.setTimeout(() => this.#checkEnd(), Math.max(0, Math.min(delay, remaining)));
  }

  // Silêncio suficiente: confirma o fim, a menos que a frase pareça incompleta (aí amplia uma vez a espera).
  #checkEnd() {
    if (this.#finished) return;
    const text = this.#fullText();
    if (text && looksIncomplete(text) && this.#extensions < MAX_SILENCE_EXTENSIONS) {
      this.#extensions += 1;
      this.#armConfirmTimer(this.#extendedSilenceMs);
      return;
    }
    this.#confirmEnd();
  }

  // Fim confirmado (por silêncio, pelo limite de segurança ou por stop() manual): entrega o texto acumulado.
  #confirmEnd() {
    if (this.#finished) return;
    this.#finished = true;
    window.clearTimeout(this.#awaitTimer);
    window.clearTimeout(this.#silenceTimer);
    window.clearTimeout(this.#maxTimer);
    if (this.#awaitingEnd) {
      this.#awaitingEnd = false;
      this.#handlers.onAwaitingEnd?.(false);
    }
    const text = this.#fullText();
    if (this.#engine) {
      try { this.#engine.stop(); } catch { /* já parado */ }
    }
    if (text) this.#handlers.onResult?.(text);
    this.#finishCapture();
  }

  #onEngineEnd() {
    this.#listening = false;
    if (this.#finished || !this.#active) return;
    if (this.#fatalErrorCode) {
      const code = this.#fatalErrorCode;
      this.#finished = true;
      window.clearTimeout(this.#awaitTimer);
      window.clearTimeout(this.#silenceTimer);
      window.clearTimeout(this.#maxTimer);
      this.#handlers.onError?.(code);
      this.#finishCapture();
      return;
    }
    if (!this.#progress.audio) {
      // Nunca conseguiu abrir o microfone: não é silêncio, é falha real de captura.
      this.#finished = true;
      window.clearTimeout(this.#maxTimer);
      this.#handlers.onError?.("no-audio");
      this.#finishCapture();
      return;
    }
    if (this.#networkErrorPending) {
      this.#finished = true;
      window.clearTimeout(this.#maxTimer);
      this.#handlers.onError?.("network");
      this.#finishCapture();
      return;
    }
    if (this.#progress.speech && !this.#fullText()) {
      // Houve fala de verdade (speechstart), mas o reconhecimento nunca devolveu nenhum texto: falha real
      // do serviço de reconhecimento, não um silêncio a tolerar — reiniciar não ajudaria.
      this.#finished = true;
      window.clearTimeout(this.#awaitTimer);
      window.clearTimeout(this.#silenceTimer);
      window.clearTimeout(this.#maxTimer);
      this.#handlers.onError?.("no-result");
      this.#finishCapture();
      return;
    }
    // O motor parou por conta própria (ex.: o navegador tem seu próprio limite interno de silêncio), mas
    // ainda não confirmamos o fim da pergunta: continua a MESMA captura, sem avisar a interface nem perder
    // o que já foi reconhecido.
    if (Date.now() < this.#deadline && this.#restartGuard < MAX_INNER_RESTARTS) {
      this.#restartGuard += 1;
      window.setTimeout(() => {
        if (!this.#finished && this.#active) this.#startEngine();
      }, 120);
      return;
    }
    this.#confirmEnd();
  }

  #onEngineError(event) {
    if (this.#finished) return;
    this.#progress.error = true;
    const code = event.error;
    if (FATAL_RECOGNITION_ERRORS.has(code)) this.#fatalErrorCode = code;
    else if (code === "network") this.#networkErrorPending = true;
    // Demais códigos (no-speech, aborted etc.) são decididos em onEngineEnd: silêncio não é erro aqui.
  }

  #finishCapture() {
    this.#active = false;
    this.#listening = false;
    this.#handlers.onEnd?.();
  }

  // Encerramento manual (ex.: botão "Parar" do diagnóstico): confirma o fim com o que já foi ouvido.
  stop() {
    if (!this.#active) return;
    this.#confirmEnd();
  }

  // Descarta a captura em andamento sem entregar texto (ex.: a conversa foi encerrada pelo visitante/operador).
  abort() {
    if (this.#finished) {
      if (this.#engine) { try { this.#engine.abort(); } catch { /* já parado */ } }
      return;
    }
    this.#progress.aborted = true;
    this.#finished = true;
    window.clearTimeout(this.#awaitTimer);
    window.clearTimeout(this.#silenceTimer);
    window.clearTimeout(this.#maxTimer);
    if (this.#awaitingEnd) {
      this.#awaitingEnd = false;
      this.#handlers.onAwaitingEnd?.(false);
    }
    if (this.#engine) { try { this.#engine.abort(); } catch { /* já parado */ } }
    this.#finishCapture();
  }
}

// Nomes de vozes conhecidas em português (Windows/Edge e vozes "Online (Natural)" da Microsoft, mais variações
// comuns de outros sistemas). O SpeechSynthesis da Web não informa o gênero da voz: a identificação é pelo nome.
// Vozes femininas NUNCA são escolhidas, nem como alternativa; se nenhuma voz masculina compatível existir, a função
// avisa o operador em vez de escolher uma voz feminina silenciosamente (ver #refreshVoice).
const MALE_VOICE_NAMES = [
  // Vozes "Online (Natural)" da Microsoft em português do Brasil (Windows 11 / Edge) — preferidas, por soarem naturais
  "antonio", "donato", "fabio", "humberto", "julio", "macerio", "nicolau", "valerio",
  // Outras vozes masculinas em português (Portugal, desktop/SAPI, ou de outros fornecedores)
  "daniel", "duarte", "diego", "bruno", "carlos", "eduardo", "felipe", "fernando", "gustavo", "joaquim",
  "marcelo", "mario", "pedro", "rafael", "ricardo", "rodrigo", "thiago", "tiago",
];
const FEMALE_VOICE_NAMES = [
  "francisca", "brenda", "elza", "giovanna", "leila", "leticia", "manuela", "thalita", "yara",
  "maria", "luciana", "camila", "vitoria", "heloisa", "helena", "ines", "joana", "raquel", "catarina",
];
// Vozes "Online"/"Natural" da Microsoft soam bem mais naturais do que as vozes locais (SAPI5) mais antigas.
const NATURAL_HINT = /online|natural|neural/i;

function normalizeVoiceName(name) {
  return String(name || "")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase();
}

function matchesAny(normalizedName, list) {
  return list.some((hint) => normalizedName.includes(hint));
}

function isKnownMaleVoice(voice) {
  const name = normalizeVoiceName(voice.name);
  if (matchesAny(name, FEMALE_VOICE_NAMES)) return false; // nunca tratar como masculina uma voz com nome feminino conhecido
  return matchesAny(name, MALE_VOICE_NAMES);
}

// Prioriza vozes "Online (Natural)" (mais naturais e expressivas) e, dentro delas, a ordem de MALE_VOICE_NAMES.
function voiceRank(voice) {
  const name = normalizeVoiceName(voice.name);
  const naturalBonus = NATURAL_HINT.test(voice.name) ? 1000 : 0;
  const knownIndex = MALE_VOICE_NAMES.findIndex((hint) => name.includes(hint));
  return naturalBonus + (knownIndex === -1 ? 0 : MALE_VOICE_NAMES.length - knownIndex);
}

function bestMaleVoice(voices) {
  const candidates = voices.filter(isKnownMaleVoice);
  candidates.sort((a, b) => voiceRank(b) - voiceRank(a));
  return candidates[0] || null;
}

export const SPEECH_RATE_MIN = 0.75;
export const SPEECH_RATE_MAX = 2.0;
export const SPEECH_RATE_DEFAULT = 1.15; // ritmo de conversa mais natural que o padrão anterior (0.95)

// Síntese de voz: voz MASCULINA em português quando disponível, velocidade ajustável, interrupção e repetição.
export class SpeechOutput {
  #voice = null;
  #current = null;
  #lastText = "";
  #rate;
  #volume;
  #lang;
  #maleFound = false;
  #fallbackRegion = false;
  #otherLanguageMaleNames = [];
  #onVoiceChange;

  constructor({ lang = "pt-BR", rate = SPEECH_RATE_DEFAULT, volume = 1, onVoiceChange = null } = {}) {
    this.#lang = lang;
    this.#rate = this.#clampRate(rate);
    this.#volume = volume;
    this.#onVoiceChange = onVoiceChange;
    if (this.supported) {
      this.#refreshVoice();
      window.speechSynthesis.addEventListener?.("voiceschanged", () => this.#refreshVoice());
    } else {
      this.#onVoiceChange?.(null, false, []); // navegador sem síntese de voz: avisa quem está ouvindo (ex.: painel do operador)
    }
  }

  get supported() {
    return Boolean(window.speechSynthesis) && typeof window.SpeechSynthesisUtterance === "function";
  }

  get speaking() {
    return this.#current !== null;
  }

  get hasText() {
    return this.#lastText !== "";
  }

  #clampRate(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return this.#rate ?? SPEECH_RATE_DEFAULT;
    return Math.min(SPEECH_RATE_MAX, Math.max(SPEECH_RATE_MIN, n));
  }

  get rate() {
    return this.#rate;
  }

  set rate(value) {
    this.#rate = this.#clampRate(value);
  }

  // { name, lang, exact, male: true, fallbackRegion } quando há voz MASCULINA selecionada;
  // null quando nenhuma voz masculina compatível foi encontrada (nunca retorna uma voz feminina).
  get voiceInfo() {
    if (!this.#voice) return null;
    return {
      name: this.#voice.name,
      lang: this.#voice.lang,
      exact: this.#isPtBr(this.#voice),
      male: true,
      fallbackRegion: this.#fallbackRegion,
    };
  }

  // Nomes de vozes masculinas instaladas em outros idiomas (não usadas, para não comprometer a pronúncia do pt-BR).
  get otherLanguageMaleVoiceNames() {
    return [...this.#otherLanguageMaleNames];
  }

  #isPtBr(voice) {
    return voice.lang.toLowerCase().replace("_", "-") === "pt-br";
  }

  #refreshVoice() {
    const voices = window.speechSynthesis.getVoices();
    const ptBr = voices.filter((voice) => this.#isPtBr(voice));
    const ptAny = voices.filter((voice) => voice.lang.toLowerCase().startsWith("pt"));
    const otherLang = voices.filter((voice) => !voice.lang.toLowerCase().startsWith("pt"));

    let picked = bestMaleVoice(ptBr);
    this.#fallbackRegion = false;
    if (!picked) {
      // Sem voz masculina em pt-BR: tenta outra região de português (ex.: pt-PT) antes de desistir.
      picked = bestMaleVoice(ptAny);
      this.#fallbackRegion = Boolean(picked);
    }
    this.#voice = picked; // nunca uma voz feminina: se nada masculino em português existir, fica null (ver voiceInfo)
    this.#maleFound = Boolean(picked);
    this.#otherLanguageMaleNames = bestMaleVoice(otherLang)
      ? [...new Set(otherLang.filter(isKnownMaleVoice).map((v) => v.name))].slice(0, 3)
      : [];
    this.#onVoiceChange?.(this.voiceInfo, true, this.#otherLanguageMaleNames);
  }

  speak(text, { onStart, onEnd, onError } = {}) {
    if (!this.supported || !text) return false;
    this.cancel();
    this.#lastText = text;
    const utterance = new window.SpeechSynthesisUtterance(text);
    utterance.lang = this.#voice ? this.#voice.lang : this.#lang;
    if (this.#voice) {
      try {
        utterance.voice = this.#voice;
      } catch {
        // voz inválida: usa a voz padrão do navegador para o idioma
      }
    }
    utterance.rate = this.#rate;
    utterance.volume = this.#volume;
    // Eventos de falas antigas (canceladas) são ignorados.
    const isCurrent = () => this.#current === utterance;
    utterance.onstart = () => {
      if (isCurrent()) onStart?.();
    };
    utterance.onend = () => {
      if (!isCurrent()) return;
      this.#current = null;
      onEnd?.();
    };
    utterance.onerror = (event) => {
      if (!isCurrent()) return;
      this.#current = null;
      onError?.(event.error);
      onEnd?.();
    };
    this.#current = utterance;
    this.#onCancel = onEnd;
    window.speechSynthesis.speak(utterance);
    return true;
  }

  #onCancel = null;

  // Interrompe a fala atual e avisa quem estava ouvindo (onEnd) para restaurar a interface.
  cancel() {
    if (!this.supported) return;
    const wasSpeaking = this.#current !== null;
    const notify = this.#onCancel;
    this.#current = null;
    this.#onCancel = null;
    window.speechSynthesis.cancel();
    if (wasSpeaking) notify?.();
  }

  repeat(handlers) {
    return this.speak(this.#lastText, handlers);
  }
}
