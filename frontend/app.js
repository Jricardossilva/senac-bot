import {
  SPEECH_INPUT_DEFAULTS,
  SPEECH_RATE_DEFAULT,
  SPEECH_RATE_MAX,
  SPEECH_RATE_MIN,
  SpeechInput,
  SpeechOutput,
  detectMicrophones,
  queryMicPermission,
  requestMicrophoneAccess
} from "/assets/speech.js";
import { STATES, VoiceConversation } from "/assets/conversation.js";
import { initDiagnostics } from "/assets/diagnostics.js";
import { runDemo } from "/assets/demo.js";
import { initEvents } from "/assets/events.js";
import { authFetch } from "/assets/auth.js";
import { initKnowledgePanel } from "/assets/knowledge.js";

const $ = (selector) => document.querySelector(selector);

// O avatar é definido uma única vez (<template id="avatar-template">) e montado em cada palco.
function mountAvatars() {
  const template = $("#avatar-template");
  document.querySelectorAll("[data-avatar]").forEach((container) => {
    const svg = template.content.firstElementChild.cloneNode(true);
    svg.setAttribute("aria-label", container.dataset.avatar);
    container.replaceChildren(svg);
  });
}
mountAvatars();


const expressionLabels = {
  neutral: "Neutro",
  happy: "Feliz",
  curious: "Curioso",
  thinking: "Pensando",
  speaking: "Falando",
  surprised: "Surpreso",
  sad: "Triste",
  disconnected: "Desconectado"
};
const movementLabels = {
  idle: "Aguardando",
  look_left: "Olhando para a esquerda",
  look_right: "Olhando para a direita",
  tilt_head: "Inclinando a cabeça",
  left_arm: "Movendo o braço esquerdo",
  right_arm: "Movendo o braço direito",
  wave: "Cumprimentando",
  celebrate: "Comemorando",
  wheels_forward: "Rodas para frente",
  wheels_backward: "Rodas para trás",
  spin: "Girando",
  stop: "Parado"
};
const headLabels = { centered: "Centralizada", left: "Para a esquerda", right: "Para a direita", tilted: "Inclinada" };
const wheelLabels = { stopped: "Paradas", forward: "Para frente", backward: "Para trás", turning: "Girando" };
const aiStatusInfo = {
  not_configured: ["Não configurado", "Usando respostas locais", "GEMINI NÃO CONFIGURADO · RESPOSTAS LOCAIS"],
  configured: ["Configurado", "Ainda não verificado", "GEMINI CONFIGURADO · MODO HÍBRIDO"],
  available: ["Disponível", "Respondendo normalmente", "GEMINI DISPONÍVEL · MODO HÍBRIDO"],
  invalid_key: ["Chave inválida", "Verifique GEMINI_API_KEY no .env", "GEMINI COM CHAVE INVÁLIDA · RESPOSTAS LOCAIS"],
  rate_limited: ["Limite atingido", "Usando respostas locais temporariamente", "GEMINI NO LIMITE · RESPOSTAS LOCAIS"],
  unavailable: ["Indisponível", "Sem conexão ou serviço fora do ar", "GEMINI INDISPONÍVEL · RESPOSTAS LOCAIS"],
  model_unavailable: ["Modelo indisponível", "Verifique GEMINI_MODEL no .env", "MODELO GEMINI INDISPONÍVEL · RESPOSTAS LOCAIS"]
};
const sourceLabels = { local: "Resposta local", gemini: "Gemini (IA)", fallback: "Contingência local", knowledge: "Base de conhecimento", event: "Evento ativo", external: "Pesquisa externa", policy: "Política de segurança", guidance: "Orientação de cursos", demo: "Demonstração" };
const permissionLabels = { granted: "Permitido", denied: "Negado", prompt: "Será solicitado", unknown: "Desconhecido" };

const sessionId = window.crypto && crypto.randomUUID ? crypto.randomUUID() : String(Date.now());
const visitorState = $("#visitor-state");
const visitorStateLabel = $("#visitor-state-label");
const connection = $(".connection");
const connectionLabel = $("#connection-label");
const messages = $("#messages");
const conversationButton = $("#conversation-button");
const events = initEvents();
const knowledgePanel = initKnowledgePanel();

// Evento ativo: o visitante só recebe nome, tema, boas-vindas e perguntas sugeridas (/api/event/active).
const eventDefaults = {
  eyebrow: $("#visitor-eyebrow").textContent,
  tryEyebrow: $("#try-eyebrow").textContent,
  tryTitle: $("#try-title").textContent,
  intro: $("#visitor-intro").textContent,
  questions: [...document.querySelectorAll("#try-list q")].map((q) => q.textContent)
};
let currentEventKey = "";

function setTryQuestions(questions) {
  const list = $("#try-list");
  list.replaceChildren(...questions.map((text) => {
    const item = document.createElement("li");
    const quote = document.createElement("q");
    quote.textContent = text;
    item.append(quote);
    return item;
  }));
}

function applyEventInfo(info) {
  const active = Boolean(info && info.active);
  const key = active ? [info.name, info.welcome, (info.suggested_questions || []).join("|")].join("\u0001") : "";
  if (key === currentEventKey) return;
  currentEventKey = key;
  WELCOME = active ? info.welcome : DEFAULT_WELCOME;
  $("#visitor-eyebrow").textContent = active ? `SENAC PARAÍBA · ${info.name.toUpperCase()}` : eventDefaults.eyebrow;
  $("#try-eyebrow").textContent = active ? `${info.name.toUpperCase()}` : eventDefaults.tryEyebrow;
  $("#try-title").textContent = active ? `Converse sobre o evento ${info.name} e sobre as oportunidades do Senac.` : eventDefaults.tryTitle;
  $("#visitor-intro").textContent = active ? `Sou o assistente virtual do Senac Paraíba. Toque no botão e converse comigo por voz: pergunte sobre o evento ${info.name} e sobre educação profissional.` : eventDefaults.intro;
  $("#footer-event").textContent = active ? ` · ${info.name}` : "";
  setTryQuestions(active && (info.suggested_questions || []).length ? info.suggested_questions : eventDefaults.questions);
  // Só troca a mensagem de boas-vindas se ainda não houve conversa (nunca apaga legendas em andamento).
  if (!conversation.active && messages.querySelectorAll(".message").length <= 1) resetCaptions();
}

async function refreshEventInfo() {
  try {
    const response = await fetch("/api/event/active");
    if (response.ok) applyEventInfo(await response.json());
  } catch {
    // sem conexão: mantém o que já está na tela
  }
}
const voiceHint = $("#voice-hint");
const stopSpeechButton = $("#stop-speech");
const voiceSupported = Boolean(window.SpeechRecognition || window.webkitSpeechRecognition);
const robots = document.querySelectorAll(".robot");

const demoSkipButton = $("#demo-skip");
const preflightButton = $("#run-preflight");

let requestPending = false;
let demoRunning = false;
let questionsSkipped = false;
let preflightDone = false;
let statusSocketOpen = false;
let errorResetTimer;
let sensorDebounce;
let lastConversationState = null;
let conversationStartedAt = 0;

const IDLE_LABEL = "Toque em INICIAR CONVERSA para falar comigo";
const DEFAULT_WELCOME = "Olá! Eu sou o SENAC BOT. Toque em INICIAR CONVERSA e me pergunte o que quiser.";
let WELCOME = DEFAULT_WELCOME; // muda com o evento ativo (somente o que o servidor publica para o visitante)

/* ---------- Voz: sempre masculina em português (ver speech.js); velocidade ajustável e persistida ---------- */

function readStoredSpeechRate() {
  try {
    const raw = Number(localStorage.getItem("senac-bot-speech-rate"));
    return Number.isFinite(raw) && raw >= SPEECH_RATE_MIN && raw <= SPEECH_RATE_MAX ? raw : SPEECH_RATE_DEFAULT;
  } catch {
    return SPEECH_RATE_DEFAULT; // sem armazenamento disponível: usa o padrão só para esta sessão
  }
}

function describeVoice(info) {
  const regionNote = info.exact ? "" : info.fallbackRegion ? " — sem voz masculina em pt-BR; usando português de outra região" : "";
  return `${info.name} (${info.lang})${regionNote}`;
}

// Chamado pela própria SpeechOutput sempre que a lista de vozes do navegador muda (ver #refreshVoice em speech.js) —
// inclusive de forma síncrona durante a construção de `speechOutput`, por isso recebe tudo pelos parâmetros, sem
// referenciar essa variável aqui (ela ainda não existiria nesse primeiro instante).
function refreshVoiceCard(info, supported, otherLanguageMaleNames = []) {
  const summary = $("#voice-summary");
  if (!summary) return;
  if (!supported) {
    summary.dataset.ready = "false";
    summary.textContent = "Este navegador não tem síntese de voz. As respostas do SENAC BOT continuam na tela.";
  } else if (info) {
    summary.dataset.ready = "true";
    summary.textContent = `Voz masculina selecionada: ${describeVoice(info)}.`;
  } else {
    summary.dataset.ready = "false";
    summary.textContent =
      "Nenhuma voz masculina em português foi encontrada neste computador; a síntese usará a voz padrão do navegador (pode não ser masculina)." +
      (otherLanguageMaleNames.length
        ? ` Há voz(es) masculina(s) instalada(s) em outro idioma (${otherLanguageMaleNames.join(", ")}), mas não são usadas, para manter a pronúncia correta do português.`
        : " Instale uma voz masculina em português em Configurações do Windows > Hora e idioma > Fala.");
  }
  const test = $("#voice-test");
  if (test) test.disabled = !supported;
}

const speechOutput = new SpeechOutput({ lang: "pt-BR", rate: readStoredSpeechRate(), volume: 1, onVoiceChange: refreshVoiceCard });
const diagnostics = initDiagnostics(speechOutput, () => visitorLocationStatus);

const voiceRateInput = $("#voice-rate");
const voiceRateValue = $("#voice-rate-value");
if (voiceRateInput) {
  voiceRateInput.min = String(SPEECH_RATE_MIN);
  voiceRateInput.max = String(SPEECH_RATE_MAX);
  voiceRateInput.value = String(speechOutput.rate);
  if (voiceRateValue) voiceRateValue.textContent = `${speechOutput.rate.toFixed(2)}x`;
  voiceRateInput.addEventListener("input", () => {
    speechOutput.rate = voiceRateInput.valueAsNumber;
    if (voiceRateValue) voiceRateValue.textContent = `${speechOutput.rate.toFixed(2)}x`;
    try {
      localStorage.setItem("senac-bot-speech-rate", String(speechOutput.rate));
    } catch {
      // sem armazenamento disponível: a velocidade vale só para esta sessão
    }
  });
}
$("#voice-test")?.addEventListener("click", () => {
  const button = $("#voice-test");
  button.disabled = true;
  const original = button.textContent;
  button.textContent = "Testando...";
  const restore = () => {
    button.disabled = !speechOutput.supported;
    button.textContent = original;
  };
  if (!speechOutput.speak("Olá! Eu sou o SENAC BOT. Esta é a minha voz, em português do Brasil.", { onEnd: restore, onError: restore })) {
    restore();
  }
});

/* ---------- Estado visual do visitante ---------- */

function setVisitorState(state, label = state) {
  visitorState.dataset.state = state;
  visitorStateLabel.textContent = label;
  // Escuta e fala acendem os fones laranja do avatar (efeito visual, sem comando ao robô).
  const voice = state === "Ouvindo" ? "listening" : state === "Falando" ? "speaking" : "";
  robots.forEach((robot) => {
    robot.dataset.voice = voice;
  });
  window.clearTimeout(errorResetTimer);
  if (state === "Erro") {
    errorResetTimer = window.setTimeout(() => {
      if (visitorState.dataset.state === "Erro" && !conversation.active) setVisitorState("Aguardando", IDLE_LABEL);
    }, 7000);
  }
}

function showView(name) {
  document.querySelectorAll(".view").forEach((view) => {
    const active = view.id === name;
    view.hidden = !active;
    view.classList.toggle("active", active);
  });
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === name);
    if (button.classList.contains("nav-button")) {
      button.setAttribute("aria-current", button.dataset.view === name ? "page" : "false");
    }
  });
  if (name !== "visitor" && conversation.active && !demoRunning) conversation.stop("view");
  if (name === "operator") {
    refreshStatus();
    refreshMicrophoneStatus();
    refreshKnowledge();
    events.refresh();
    if (!preflightDone) runPreflight();
  }
  if (name === "diagnostics") diagnostics.refresh();
  if (name === "visitor") refreshEventInfo();
}

document.querySelectorAll("[data-view]").forEach((button) => {
  button.addEventListener("click", () => showView(button.dataset.view));
});

// Links oficiais (programação, matrícula): ficam na tela e abrem em outra aba, sem tirar o visitante da conversa.
function withLinks(paragraph, links) {
  const valid = (Array.isArray(links) ? links : []).filter((link) => link && /^https:\/\/[^\s]+$/.test(link.url || ""));
  if (!valid.length) return paragraph;
  const list = document.createElement("div");
  list.className = "message-links";
  for (const link of valid) {
    const anchor = document.createElement("a");
    anchor.href = link.url;
    anchor.target = "_blank";
    anchor.rel = "noopener noreferrer";
    anchor.textContent = link.label || "Site oficial";
    list.append(anchor);
  }
  const column = document.createElement("div");
  column.className = "message-column";
  column.append(paragraph, list);
  return column;
}

function appendMessage(text, kind, source, links) {
  const wrapper = document.createElement("div");
  wrapper.className = `message ${kind}-message`;
  if (kind === "bot") {
    const avatar = document.createElement("span");
    avatar.className = "message-avatar";
    avatar.setAttribute("aria-hidden", "true");
    wrapper.append(avatar);
  }
  const paragraph = document.createElement("p");
  paragraph.textContent = text;
  if (source && sourceLabels[source]) {
    const badge = document.createElement("small");
    badge.className = "message-source";
    badge.dataset.source = source;
    badge.textContent = sourceLabels[source];
    paragraph.append(badge);
  }
  wrapper.append(withLinks(paragraph, links));
  messages.append(wrapper);
  messages.scrollTop = messages.scrollHeight;
}

async function postJson(url, body) {
  const response = await authFetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {})
  });
  let result = {};
  try {
    result = await response.json();
  } catch {
    // resposta sem JSON: segue com mensagem genérica abaixo
  }
  if (!response.ok) {
    const detail = Array.isArray(result.detail) ? "Dados inválidos." : result.detail;
    throw new Error(detail || "Não foi possível concluir a operação.");
  }
  return result;
}

/* ---------- Conexão e estado vindo do backend ---------- */

function updateConnection(online) {
  connection.classList.toggle("offline", !online);
  connectionLabel.textContent = online ? "Sistema conectado" : "Sistema offline";
  if (!online) setVisitorState("Offline", "Sem conexão com o servidor");
}

function applyRobot(status) {
  const sensors = status.sensors;
  robots.forEach((robot) => {
    robot.dataset.action = status.simulator_action;
    robot.dataset.expression = status.expression;
    robot.dataset.obstacle = String(sensors.obstacle);
    robot.dataset.connected = String(sensors.connected);
    robot.dataset.emergency = String(status.emergency_stop);
  });
  $("#robot-caption-state").textContent =
    status.simulator_action === "idle" ? "Pronto para conversar" : movementLabels[status.simulator_action];
  $("#simulator-state-label").textContent = movementLabels[status.simulator_action] || "Aguardando";
  $("#simulator-expression-label").textContent = expressionLabels[status.expression] || "Neutro";
  document.querySelectorAll(".action-chip").forEach((chip) => {
    const action = chip.dataset.action;
    chip.classList.toggle("selected", action === status.simulator_action || action === status.expression);
  });
  const distance = $("#sensor-distance");
  if (document.activeElement !== distance) distance.value = sensors.distance_cm;
  $("#sensor-distance-value").textContent = `${sensors.distance_cm} cm`;
  const connectedBox = $("#sensor-connected");
  if (document.activeElement !== connectedBox) connectedBox.checked = sensors.connected;
  $("#sensor-proximity").textContent = sensors.proximity === "near" ? "Objeto próximo" : "Longe";
  $("#sensor-obstacle").textContent = sensors.obstacle ? "Obstáculo à frente" : "Livre";
  $("#sensor-connection").textContent = sensors.connected ? "Conectado" : "Desconectado";
  const motors = status.motors;
  $("#motor-head").textContent = headLabels[motors.head] || motors.head;
  $("#motor-arms").textContent =
    motors.left_arm === "moving" && motors.right_arm === "moving"
      ? "Ambos em movimento"
      : motors.left_arm === "moving"
        ? "Esquerdo em movimento"
        : motors.right_arm === "moving"
          ? "Direito em movimento"
          : "Parados";
  $("#motor-wheels").textContent = wheelLabels[motors.wheels] || motors.wheels;
}

function updateStatus(status) {
  updateConnection(status.application === "online");
  const applicationState = $("#application-state");
  applicationState.replaceChildren(
    document.createElement("i"),
    document.createTextNode(status.application === "online" ? "Online" : "Offline")
  );
  const [aiLabel, aiDetail] = aiStatusInfo[status.ai_status] || aiStatusInfo.unavailable;
  $("#gemini-state").textContent = aiLabel;
  $("#gemini-detail").textContent = aiDetail;
  $("#check-ai").disabled = status.ai_status === "not_configured";
  $("#audio-state").textContent = speechOutput.supported ? "Disponível" : "Indisponível";
  $("#hardware-state").textContent = status.hardware_mode === "simulation" ? "Simulador local" : "Físico (LEGO)";
  $("#hardware-detail").textContent = status.hardware_error
    ? "Físico indisponível: simulador ativo"
    : status.hardware_mode === "simulation"
      ? "Sem conexão física"
      : "Hub conectado";
  document.querySelectorAll("[data-hardware-mode]").forEach((button) => {
    button.classList.toggle("selected", button.dataset.hardwareMode === status.hardware_mode);
  });
  const hardwareFeedback = $("#hardware-feedback");
  if (status.hardware_error) setFeedback(hardwareFeedback, status.hardware_error, true);
  else if (hardwareFeedback.classList.contains("error")) setFeedback(hardwareFeedback, "");
  $("#start-demo").disabled = status.demo_active || status.emergency_stop;
  $("#stop-demo").disabled = !status.demo_active;
  if (demoRunning && !status.demo_active) {
    demoRunning = false; // encerrada pelo operador, pela emergência ou ao encerrar a sessão
    speechOutput.cancel();
    conversation.stop("demo");
  }
  $("#operator-robot-state").textContent = status.robot_state;
  $("#operator-session-state").textContent = status.session_active ? "Sessão em andamento" : "Sessão encerrada";
  $("#start-session").disabled = status.session_active || status.emergency_stop;
  $("#stop-session").disabled = !status.session_active;
  const emergency = $("#emergency-button");
  emergency.textContent = status.emergency_stop ? "Parada acionada" : "Parada de emergência";
  emergency.disabled = status.emergency_stop;
  emergency.classList.toggle("emergency-active", status.emergency_stop);
  $("#emergency-release").hidden = !status.emergency_stop;
  const eventList = $("#event-list");
  eventList.replaceChildren();
  const events = status.events.length ? status.events : ["Aguardando eventos da aplicação."];
  events.forEach((event) => {
    const item = document.createElement("li");
    item.textContent = event;
    eventList.append(item);
  });
  applyRobot(status);
  if (status.emergency_stop) {
    speechOutput.cancel();
    setVisitorState("Erro", "Parada de emergência acionada");
  } else if (visitorState.dataset.state === "Offline") {
    setVisitorState("Aguardando", IDLE_LABEL);
  }
  // Encerramentos vindos do servidor: emergência ou sessão encerrada pelo operador.
  if (conversation.active) {
    if (status.emergency_stop) conversation.stop("emergency");
    else if (!status.session_active && !demoRunning && Date.now() - conversationStartedAt > 2500) {
      conversation.stop("operator");
    }
  }
  renderConversationButton();
}

async function refreshStatus() {
  try {
    const response = await fetch("/api/status");
    if (!response.ok) throw new Error("Falha ao consultar estado da aplicação.");
    updateStatus(await response.json());
  } catch {
    updateConnection(false);
  }
}

// Estado em tempo real por WebSocket; o polling HTTP só roda enquanto o socket estiver fechado.
function connectStatusSocket() {
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${location.host}/ws/status`);
  socket.addEventListener("open", () => {
    statusSocketOpen = true;
  });
  socket.addEventListener("message", (event) => {
    try {
      updateStatus(JSON.parse(event.data));
    } catch {
      // mensagem inválida é ignorada; o próximo estado corrige a tela
    }
  });
  socket.addEventListener("close", () => {
    statusSocketOpen = false;
    refreshStatus();
    window.setTimeout(connectStatusSocket, 3000);
  });
}

async function refreshMicrophoneStatus() {
  const [permission, devices] = await Promise.all([queryMicPermission(), detectMicrophones()]);
  $("#microphone-state").textContent = !voiceSupported
    ? "Indisponível"
    : devices.supported && devices.count === 0
      ? "Sem microfone"
      : permissionLabels[permission];
  $("#microphone-detail").textContent = !voiceSupported
    ? "Navegador sem reconhecimento de voz"
    : devices.supported
      ? `${devices.count} dispositivo(s) de entrada detectado(s)`
      : "Dispositivos não puderam ser listados";
}

function setFeedback(element, message, isError = false) {
  element.textContent = message;
  element.classList.toggle("error", isError);
}

/* ---------- Comandos do robô (sempre via controlador no backend) ---------- */

// Comandos automáticos da conversa: falhas não interrompem o diálogo.
async function conversationCommand(action) {
  try {
    updateStatus(await postJson("/api/simulator/action", { action, origin: "conversation" }));
  } catch {
    // o robô pode estar bloqueado (emergência/desconectado); o chat continua funcionando
  }
}

async function performControl(url, feedback, body) {
  feedback.classList.remove("error");
  feedback.textContent = "Enviando comando...";
  try {
    updateStatus(await postJson(url, body));
    setFeedback(feedback, "Comando concluído.");
  } catch (error) {
    if (!(error instanceof TypeError)) await refreshStatus();
    setFeedback(feedback, error.message, true);
  }
}

/* ---------- Conversa por voz ---------- */

const sleep = (ms) => new Promise((resolve) => window.setTimeout(resolve, ms));
const readingMs = (text) => text.split(/\s+/).length * 380 + 800;

/* ---------- Localização do visitante (só para calcular a unidade mais próxima) ---------- */
// Guardada só em memória, nunca em localStorage ou no backend além da requisição em curso (regra de
// privacidade do pedido: não persistir localização sem necessidade). "status" alimenta só o diagnóstico
// do operador (nunca mostra coordenadas, só se a permissão foi concedida/negada/indisponível).
let visitorLocation = null; // { lat, lon } | null
let visitorLocationStatus = "pendente"; // pendente | concedida | negada | indisponivel

function requestVisitorLocation() {
  if (!("geolocation" in navigator)) {
    visitorLocationStatus = "indisponivel";
    return;
  }
  navigator.geolocation.getCurrentPosition(
    (position) => {
      visitorLocation = { lat: position.coords.latitude, lon: position.coords.longitude };
      visitorLocationStatus = "concedida";
    },
    () => {
      visitorLocation = null;
      visitorLocationStatus = "negada";
    },
    { maximumAge: 5 * 60 * 1000, timeout: 10000 }
  );
}

// Mesmo processamento de mensagens de antes (/chat); só o texto reconhecido é enviado, nunca áudio.
async function askRobot(message) {
  const body = { message, session_id: sessionId };
  if (visitorLocation) Object.assign(body, visitorLocation);
  return postJson("/chat", body);
}

const STATE_VIEW = {
  [STATES.IDLE]: ["Aguardando", IDLE_LABEL],
  [STATES.REQUESTING]: ["Solicitando", "Solicitando permissão do microfone. Se o navegador perguntar, escolha Permitir."],
  [STATES.LISTENING]: ["Ouvindo", "Estou ouvindo você. Pode falar!"],
  [STATES.PROCESSING]: ["Processando", "Estou pensando na sua pergunta..."],
  [STATES.SPEAKING]: ["Falando", "Estou respondendo..."]
};
const ERROR_TEXT = {
  "no-result": "Não consegui entender. Pode repetir?",
  "no-audio": "Não consegui abrir o microfone. Vou tentar de novo...",
  network: "Perdi a conexão para entender sua voz. Vou tentar de novo...",
  ask: "Não consegui responder agora. Pode repetir a pergunta?"
};
const UNAVAILABLE_TEXT = {
  api: "A conversa por voz não está disponível neste navegador. Chame a equipe do stand.",
  denied: "O microfone está bloqueado. Chame a equipe do stand para liberar.",
  "no-device": "Não encontrei um microfone. Chame a equipe do stand.",
  busy: "O microfone está sendo usado por outro programa. Chame a equipe do stand.",
  network: "A conversa por voz está temporariamente indisponível por falta de conexão. Tente de novo em instantes.",
  session: "O robô está em pausa agora. Chame a equipe do stand.",
  error: "A conversa por voz está temporariamente indisponível. Tente de novo em instantes."
};
const ENDED_TEXT = {
  user: "Conversa encerrada. Obrigado pela visita!",
  idle: "Conversa encerrada por inatividade. Toque em INICIAR CONVERSA quando quiser.",
  emergency: "O robô está em pausa. Chame a equipe do stand.",
  operator: "Conversa encerrada pela equipe. Obrigado pela visita!",
  view: "Conversa encerrada."
};
const HINT_TEXT = {
  active: "Fale normalmente, sem precisar tocar de novo a cada pergunta. Para parar, toque em ENCERRAR CONVERSA.",
  idle: "Converse por voz: não precisa tocar de novo a cada pergunta. Sua voz não é gravada."
};
// Expressão do avatar em cada estado (sempre pelo controlador, como os demais comandos).
const STATE_EXPRESSION = {
  [STATES.LISTENING]: "curious",
  [STATES.PROCESSING]: "thinking",
  [STATES.SPEAKING]: "speaking",
  [STATES.ERROR]: "surprised",
  [STATES.UNAVAILABLE]: "neutral"
};

function resetCaptions() {
  messages.replaceChildren();
  appendMessage(WELCOME, "bot");
}

function renderConversationButton() {
  const state = conversation.state;
  let mode = "start";
  if (demoRunning && !conversation.active) mode = "demo";
  else if (state === STATES.REQUESTING) mode = "wait";
  else if ([STATES.LISTENING, STATES.PROCESSING, STATES.SPEAKING, STATES.ERROR].includes(state)) mode = "stop";
  conversationButton.dataset.mode = mode;
  conversationButton.querySelector(".conversation-label").textContent = {
    start: "INICIAR CONVERSA",
    wait: "SOLICITANDO MICROFONE...",
    stop: "ENCERRAR CONVERSA",
    demo: "DEMONSTRAÇÃO EM ANDAMENTO"
  }[mode];
  conversationButton.disabled = mode === "wait" || mode === "demo";
  conversationButton.setAttribute("aria-pressed", String(mode === "stop"));
}

function updateVoiceControls() {
  stopSpeechButton.hidden = !(speechOutput.speaking || conversation.state === STATES.SPEAKING);
}

// Diagnóstico ao vivo da escuta, só para o operador (painel "Diagnóstico"); nunca aparece para o visitante.
function updateConversationDiagnostics(state, detail = {}) {
  const stateEl = document.getElementById("diag-conv-state");
  if (stateEl) {
    stateEl.textContent =
      state === STATES.LISTENING && detail.awaitingEnd
        ? "Aguardando conclusão da fala (silêncio detectado)"
        : (STATE_VIEW[state] && STATE_VIEW[state][0]) || state;
  }
}

function onConversationState(state, detail = {}) {
  let view;
  if (state === STATES.ERROR) view = ["Erro", ERROR_TEXT[detail.kind] || ERROR_TEXT["no-result"]];
  else if (state === STATES.UNAVAILABLE) view = ["Indisponivel", UNAVAILABLE_TEXT[detail.kind] || UNAVAILABLE_TEXT.error];
  else if (state === STATES.ENDED) {
    view = detail.reason === "demo" ? ["Aguardando", "Demonstração em andamento"] : ["Encerrada", ENDED_TEXT[detail.reason] || ENDED_TEXT.user];
  } else if (state === STATES.LISTENING && detail.awaitingEnd) view = ["Ouvindo", "Pode continuar, estou ouvindo!"];
  else if (state === STATES.LISTENING && detail.hint) view = ["Ouvindo", "Estou ouvindo. Pode falar quando quiser!"];
  else view = STATE_VIEW[state];
  setVisitorState(view[0], view[1]);
  voiceHint.textContent = conversation.active ? HINT_TEXT.active : HINT_TEXT.idle;
  renderConversationButton();
  updateVoiceControls();
  updateConversationDiagnostics(state, detail);

  if (state === lastConversationState && !detail.hint) return; // reinícios silenciosos não repetem comandos
  const previous = lastConversationState;
  lastConversationState = state;
  // Conversa nova do visitante começa com legendas limpas; a janela de perguntas da demonstração mantém as dela.
  if (state === STATES.REQUESTING && detail.manageSession !== false) resetCaptions();
  if (state === STATES.LISTENING && previous === STATES.REQUESTING) conversationStartedAt = Date.now();
  const expression = STATE_EXPRESSION[state];
  if (expression) conversationCommand(expression);
  if (state === STATES.ENDED && detail.reason !== "demo") {
    conversationCommand("happy");
    conversationCommand("wave"); // gesto de despedida (volta sozinho à posição neutra)
    window.setTimeout(() => {
      if (lastConversationState === STATES.ENDED) conversationCommand("neutral");
    }, 2800);
  }
}

function onConversationCaption(role, text, meta = {}) {
  if (role === "user") appendMessage(text, "user");
  else appendMessage(text, "bot", meta.source, meta.links);
}

const conversation = new VoiceConversation({
  // Tempos da detecção do fim da fala (ver speech.js): só considera que o visitante pode ter terminado
  // depois de minSilenceMs de silêncio, e só confirma depois de confirmSilenceMs — ampliado sozinho até
  // extendedSilenceMs quando a frase parece incompleta. maxSeconds é o limite de segurança da captura inteira.
  createRecognizer: (handlers) =>
    new SpeechInput(handlers, { lang: "pt-BR", ...SPEECH_INPUT_DEFAULTS, ...(window.__SENAC_SPEECH_TIMINGS__ || {}) }),
  speech: speechOutput,
  detectMicrophones,
  requestMicrophone: requestMicrophoneAccess,
  ask: askRobot,
  openSession: async () => {
    updateStatus(await postJson("/api/session/start"));
  },
  closeSession: async () => {
    updateStatus(await postJson("/api/session/stop", { session_id: sessionId }));
  },
  onState: onConversationState,
  onCaption: onConversationCaption,
  onListening: ({ partial } = {}) => {
    const el = document.getElementById("diag-conv-partial");
    if (el) el.textContent = partial || "—";
  }
}, window.__SENAC_VOICE_TIMINGS__ || {}); // gancho usado só pelos testes de interface para acelerar esperas

conversationButton.addEventListener("click", () => {
  const mode = conversationButton.dataset.mode;
  if (mode === "stop") conversation.stop("user");
  else if (mode === "start") conversation.start();
});
stopSpeechButton.addEventListener("click", () => {
  if (conversation.active) conversation.interrupt();
  else speechOutput.cancel();
});

/* ---------- Respostas faladas fora da conversa (modo demonstração) ---------- */

function finishSpeaking() {
  if (visitorState.dataset.state === "Falando") setVisitorState("Aguardando", IDLE_LABEL);
  conversationCommand("neutral");
  updateVoiceControls();
}

function speechHandlers() {
  return {
    onStart: () => {
      setVisitorState("Falando", "Estou respondendo...");
      conversationCommand("speaking");
      updateVoiceControls();
    },
    onEnd: finishSpeaking,
    onError: () => {
      voiceHint.textContent = "Não foi possível reproduzir a voz. A resposta continua disponível na tela.";
    }
  };
}

function speakReply(text) {
  if (!speechOutput.supported) {
    voiceHint.textContent = "Voz sintetizada indisponível neste navegador. Leia a resposta na tela.";
    window.setTimeout(() => conversationCommand("neutral"), 3000);
  } else if (!speechOutput.speak(text, speechHandlers())) {
    finishSpeaking();
  }
  updateVoiceControls();
}

// Pergunta usada pelo roteiro da demonstração (ex.: "Quero um desafio"); devolve o texto da resposta.
async function sendMessage(message) {
  if (!message || requestPending) return "";
  requestPending = true;
  speechOutput.cancel();
  appendMessage(message, "user");
  setVisitorState("Pensando", "Estou pensando na sua pergunta...");
  conversationCommand("thinking");
  let reply = "";
  try {
    const result = await askRobot(message);
    reply = result.response;
    appendMessage(reply, "bot", result.source, result.links);
    setVisitorState("Aguardando", IDLE_LABEL);
    speakReply(reply);
  } catch (error) {
    appendMessage(error.message, "bot");
    conversationCommand("neutral");
    if (error instanceof TypeError) {
      setVisitorState("Offline", "Sem conexão com o servidor");
      updateConnection(false);
    } else {
      setVisitorState("Erro", "Não foi possível concluir");
    }
  } finally {
    requestPending = false;
  }
  return reply;
}

/* ---------- Tela cheia ---------- */

const fullscreenButton = $("#fullscreen-button");
if (document.fullscreenEnabled) {
  fullscreenButton.addEventListener("click", async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await document.documentElement.requestFullscreen();
    } catch {
      voiceHint.textContent = "Não foi possível alternar a tela cheia neste navegador.";
    }
  });
} else {
  fullscreenButton.hidden = true;
}

/* ---------- Painel do operador e simulador ---------- */

$("#start-session").addEventListener("click", () =>
  performControl("/api/session/start", $("#operator-feedback")));
$("#stop-session").addEventListener("click", () =>
  performControl("/api/session/stop", $("#operator-feedback")));
$("#check-ai").addEventListener("click", () =>
  performControl("/api/ai/check", $("#operator-feedback")));
$("#emergency-button").addEventListener("click", () =>
  performControl("/api/emergency", $("#operator-feedback")));
$("#emergency-release").addEventListener("click", () =>
  performControl("/api/emergency", $("#operator-feedback")));

document.querySelectorAll(".action-chip").forEach((chip) => {
  chip.addEventListener("click", () =>
    performControl("/api/simulator/action", $("#simulator-feedback"), { action: chip.dataset.action }));
});

$("#sensor-distance").addEventListener("input", (event) => {
  $("#sensor-distance-value").textContent = `${event.target.value} cm`;
  window.clearTimeout(sensorDebounce);
  sensorDebounce = window.setTimeout(
    () => performControl("/api/simulator/sensors", $("#sensor-feedback"), { distance_cm: Number(event.target.value) }),
    150
  );
});
$("#sensor-connected").addEventListener("change", (event) =>
  performControl("/api/simulator/sensors", $("#sensor-feedback"), { connected: event.target.checked }));

/* ---------- Modo demonstração ---------- */

function demoSay(text) {
  appendMessage(text, "bot", "demo");
  return new Promise((resolve) => {
    let finished = false;
    const done = () => {
      if (finished) return;
      finished = true;
      window.clearTimeout(guard);
      resolve();
    };
    const guard = window.setTimeout(done, readingMs(text) + 6000);
    if (!speechOutput.supported) {
      window.setTimeout(done, readingMs(text)); // sem voz: tempo de leitura na tela
      return;
    }
    const started = speechOutput.speak(text, {
      onStart: () => {
        setVisitorState("Falando", "Respondendo por voz");
        conversationCommand("speaking");
      },
      onEnd: done,
      onError: () => {}
    });
    if (!started) done();
  });
}

async function demoChat(text) {
  const reply = await sendMessage(text);
  while (speechOutput.speaking && demoRunning) await sleep(200);
  if (reply && !speechOutput.supported) await sleep(readingMs(reply));
}

// Janela de perguntas: a conversa por voz fica aberta; sem voz disponível, o roteiro segue sem a janela.
async function demoOpenQuestions(seconds) {
  questionsSkipped = false;
  const listening = await conversation.start({ manageSession: false });
  if (!listening) return;
  let deadline = Date.now() + seconds * 1000;
  demoSkipButton.hidden = false;
  await new Promise((resolve) => {
    const timer = window.setInterval(() => {
      if (requestPending || conversation.busy) deadline = Date.now() + seconds * 1000;
      const left = Math.ceil((deadline - Date.now()) / 1000);
      if (!demoRunning || questionsSkipped || left <= 0 || !conversation.active) {
        window.clearInterval(timer);
        resolve();
        return;
      }
      if (conversation.state === STATES.LISTENING) {
        setVisitorState("Ouvindo", `Perguntas abertas: ${left} s. Pergunte ao SENAC BOT!`);
      }
    }, 250);
  });
  demoSkipButton.hidden = true;
  await conversation.stop("demo");
}

async function startDemo() {
  const feedback = $("#operator-feedback");
  if (demoRunning) return;
  try {
    updateStatus(await postJson("/api/demo/start"));
  } catch (error) {
    setFeedback(feedback, error.message, true);
    return;
  }
  setFeedback(feedback, "Demonstração em andamento. Use Encerrar demonstração para parar.");
  demoRunning = true;
  renderConversationButton();
  showView("visitor");
  let outcome = "aborted";
  try {
    outcome = await runDemo({
      active: () => demoRunning,
      setStep: (name) => setVisitorState("Aguardando", `Demonstração: ${name}`),
      command: conversationCommand,
      say: demoSay,
      chat: demoChat,
      openQuestions: demoOpenQuestions
    });
  } catch {
    setFeedback(feedback, "A demonstração foi interrompida por um erro inesperado.", true);
  } finally {
    const wasRunning = demoRunning;
    demoRunning = false;
    demoSkipButton.hidden = true;
    speechOutput.cancel();
    await conversation.stop("demo");
    renderConversationButton();
    if (wasRunning) {
      try {
        updateStatus(await postJson("/api/demo/stop"));
      } catch {
        // o estado será corrigido pela próxima atualização
      }
    }
    setVisitorState("Aguardando", IDLE_LABEL);
  }
  if (outcome === "done") setFeedback(feedback, "Demonstração concluída.");
}

demoSkipButton.addEventListener("click", () => {
  questionsSkipped = true;
});
$("#start-demo").addEventListener("click", startDemo);
$("#stop-demo").addEventListener("click", () =>
  performControl("/api/demo/stop", $("#operator-feedback")));

/* ---------- Verificação do sistema ---------- */

const checkItem = (id, label, status, message, action = "") => ({ id, label, status, message, action });

async function browserAudioChecks() {
  const [permission, devices] = await Promise.all([queryMicPermission(), detectMicrophones()]);
  const checks = [];
  if (!window.isSecureContext) {
    checks.push(checkItem("mic", "Microfone", "warning", "A página não está em localhost; o navegador bloqueia o microfone.", "Abra http://localhost:8000."));
  } else if (devices.supported && devices.count === 0) {
    checks.push(checkItem("mic", "Microfone", "warning", "Nenhum microfone detectado: a conversa por voz ficará indisponível.", "Ative o microfone em Configurações > Sistema > Som ou conecte um fone com microfone."));
  } else if (permission === "denied") {
    checks.push(checkItem("mic", "Microfone", "warning", "Permissão do microfone negada.", "Libere no cadeado do navegador e em Configurações do Windows > Privacidade e segurança > Microfone."));
  } else {
    checks.push(checkItem("mic", "Microfone", "ok", `${devices.count} microfone(s) detectado(s)` + (permission === "prompt" ? "; a permissão será pedida no primeiro uso." : ".")));
  }
  checks.push(
    voiceSupported
      ? checkItem("recognition", "Reconhecimento de voz", "ok", "Disponível (o Chrome/Edge precisa de internet para reconhecer a fala).")
      : checkItem("recognition", "Reconhecimento de voz", "warning", "Este navegador não tem reconhecimento de voz: a conversa por voz ficará indisponível.", "Use o Google Chrome ou o Microsoft Edge.")
  );
  const voice = speechOutput.voiceInfo;
  checks.push(
    !speechOutput.supported
      ? checkItem("tts", "Voz sintetizada", "warning", "Este navegador não tem síntese de voz.", "As respostas continuam na tela. Use Chrome ou Edge.")
      : !voice
        ? checkItem("tts", "Voz sintetizada", "warning", "Nenhuma voz MASCULINA em português foi encontrada; será usada a voz padrão do navegador (pode não ser masculina).", "Instale uma voz masculina em pt-BR em Configurações do Windows > Hora e idioma > Fala.")
        : checkItem("tts", "Voz sintetizada", "ok", `Voz masculina: ${voice.name} (${voice.lang})${voice.exact ? "" : " — sem voz em pt-BR, usando português de outra região"}.`)
  );
  return checks;
}

function renderPreflight(checks) {
  const list = $("#preflight-list");
  list.replaceChildren();
  checks.forEach((check) => {
    const item = document.createElement("li");
    item.dataset.status = check.status;
    const label = document.createElement("strong");
    label.textContent = check.label;
    const message = document.createElement("span");
    message.textContent = check.message;
    item.append(label, message);
    if (check.action) {
      const action = document.createElement("small");
      action.textContent = check.action;
      item.append(action);
    }
    list.append(item);
  });
  const errors = checks.filter((c) => c.status === "error").length;
  const warnings = checks.filter((c) => c.status === "warning").length;
  const summary = $("#preflight-summary");
  summary.dataset.ready = String(errors === 0);
  summary.textContent = errors
    ? "Há problemas que impedem a demonstração. Corrija os itens em vermelho."
    : warnings
      ? "Pronto para a demonstração, com avisos: onde indicado, o robô usa a contingência local."
      : "Tudo pronto para a demonstração.";
}

async function runPreflight() {
  preflightDone = true;
  preflightButton.disabled = true;
  $("#preflight-summary").textContent = "Verificando internet, Gemini, hardware e áudio...";
  $("#preflight-summary").dataset.ready = "";
  let server;
  try {
    server = await postJson("/api/preflight");
  } catch (error) {
    server = {
      checks: [checkItem("server", "Servidor", "error", error.message || "O servidor não respondeu.", "Confira se o scripts\\run.ps1 está em execução.")]
    };
  }
  renderPreflight([...server.checks, ...(await browserAudioChecks())]);
  preflightButton.disabled = false;
  refreshStatus();
}

preflightButton.addEventListener("click", runPreflight);
document.querySelectorAll("[data-hardware-mode]").forEach((button) => {
  button.addEventListener("click", () =>
    performControl("/api/hardware/mode", $("#hardware-feedback"), { mode: button.dataset.hardwareMode }));
});

/* ---------- Origem das respostas (apenas uso técnico do operador) ---------- */

const sourceToggle = $("#toggle-source");
try {
  sourceToggle.checked = localStorage.getItem("senac-bot-show-source") === "1";
} catch {
  // armazenamento do navegador indisponível: segue com o padrão (oculto)
}
document.body.classList.toggle("show-source", sourceToggle.checked);
sourceToggle.addEventListener("change", () => {
  document.body.classList.toggle("show-source", sourceToggle.checked);
  try {
    localStorage.setItem("senac-bot-show-source", sourceToggle.checked ? "1" : "0");
  } catch {
    // sem persistência; vale apenas até recarregar a página
  }
});

/* ---------- Base de conhecimento (somente operador) ---------- */

function knowledgeItem(status, label, message) {
  const item = document.createElement("li");
  item.dataset.status = status;
  const strong = document.createElement("strong");
  strong.textContent = label;
  const span = document.createElement("span");
  span.textContent = message;
  item.append(strong, span);
  return item;
}

async function refreshKnowledge() {
  const summary = $("#knowledge-summary");
  const list = $("#knowledge-list");
  try {
    const response = await authFetch("/api/knowledge/status");
    const k = await response.json();
    list.replaceChildren();
    if (!k.loaded) {
      summary.dataset.ready = "false";
      summary.textContent = "A base de conhecimento não foi carregada.";
      (k.errors || []).slice(0, 5).forEach((error) => list.append(knowledgeItem("error", "Erro", error)));
      return;
    }
    const by = k.by_status;
    summary.dataset.ready = "true";
    summary.textContent = `${k.entries} entradas · ${by.verified} verificadas · ${by.review} a confirmar · ${by.stale} datadas ou vencidas · ${by.pending} pendentes · última consulta: ${k.last_consulted}`;
    k.sources.filter((s) => s.needs_review).forEach((s) =>
      list.append(knowledgeItem("warning", s.name, "A página oficial mudou desde a última revisão: confira o conteúdo e registre com --ack.")));
    k.sources.filter((s) => s.failures >= 3).forEach((s) =>
      list.append(knowledgeItem("warning", s.name, `Falhas seguidas na consulta (${s.error || "erro"}); mantida a última versão válida.`)));
    k.stale.filter((e) => !e.id.startsWith("news-")).forEach((e) =>
      list.append(knowledgeItem("warning", e.title, `Informação vencida (${e.valid_until || "por idade"}): consultar de novo.`)));
    const never = k.sources.filter((s) => !s.last_checked).length;
    if (never) list.append(knowledgeItem("warning", "Fontes nunca consultadas", `${never} de ${k.sources.length}. Rode scripts\\atualizar-conhecimento.ps1.`));
    knowledgePanel.render(k); // estatísticas e o cartão de pendências (dados reais de /api/knowledge/status)
    knowledgePanel.refreshPortal();
  } catch {
    summary.dataset.ready = "false";
    summary.textContent = "Não foi possível consultar o estado da base.";
  }
}
$("#refresh-knowledge").addEventListener("click", refreshKnowledge);

/* ---------- Teste de mensagem (somente operador) ---------- */

$("#op-test-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = $("#op-test-message");
  const text = input.value.trim();
  if (!text) return;
  const output = $("#op-test-reply");
  output.textContent = "Consultando...";
  try {
    const result = await askRobot(text);
    const used = result.knowledge && result.knowledge.length ? `; entradas: ${result.knowledge.join(", ")}` : "";
    output.textContent = `${result.response} (origem: ${sourceLabels[result.source] || result.source}${used})`;
    input.value = "";
  } catch (error) {
    output.textContent = error.message;
  }
});

/* ---------- Inicialização ---------- */

onConversationState(STATES.IDLE);
refreshStatus();
refreshMicrophoneStatus();
refreshEventInfo();
connectStatusSocket();
requestVisitorLocation(); // pedida uma vez, na abertura da aplicação; nunca bloqueia a tela nem a conversa
window.setInterval(() => {
  if (!statusSocketOpen) refreshStatus();
}, 5000);
window.setInterval(refreshEventInfo, 30000); // o operador pode ativar/desativar um evento a qualquer momento
window.addEventListener("pagehide", () => {
  conversation.stop("view"); // libera o microfone ao fechar ou recarregar a página
  speechOutput.cancel();
});
