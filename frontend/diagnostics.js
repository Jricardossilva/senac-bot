// Tela de diagnóstico de áudio. A captura de teste só dura alguns segundos e nada é gravado:
// o fluxo do microfone é lido apenas para medir o nível e é encerrado em seguida.
import { SPEECH_INPUT_DEFAULTS, SpeechInput, describeSpeechError, detectMicrophones, queryMicPermission } from "/assets/speech.js";

const LEVEL_TEST_SECONDS = 5;
const PERMISSION_LABELS = {
  granted: "Concedida",
  denied: "Negada — libere o microfone no navegador e no Windows",
  prompt: "Ainda não solicitada (será pedida ao testar)",
  unknown: "Não foi possível consultar"
};

const LOCATION_LABELS = {
  pendente: "Pedindo permissão...",
  concedida: "Concedida (usada só para calcular a unidade mais próxima; nunca mostrada aqui)",
  negada: "Negada — o assistente pedirá cidade/bairro quando for preciso",
  indisponivel: "Indisponível neste navegador"
};

export function initDiagnostics(speechOutput, getLocationStatus) {
  const $ = (id) => document.getElementById(id);
  let levelRunning = false;

  const recognizer = new SpeechInput(
    {
      onStart: () => ($("diag-capture").textContent = "Ouvindo (reconhecimento)..."),
      onPartial: (text) => {
        $("diag-text").textContent = text || "—";
        if ($("diag-capture").textContent.startsWith("Ouvindo") || $("diag-capture").textContent.startsWith("Aguardando")) {
          $("diag-capture").textContent = "Ouvindo (reconhecimento)...";
        }
      },
      onAwaitingEnd: (flag) => {
        if (flag) $("diag-capture").textContent = "Aguardando conclusão da fala (silêncio detectado)...";
        else if ($("diag-capture").textContent.startsWith("Aguardando")) $("diag-capture").textContent = "Ouvindo (reconhecimento)...";
      },
      onResult: (text) => {
        $("diag-text").textContent = text;
        $("diag-capture").textContent = "Fim da fala confirmado";
      },
      onError: (code) => {
        const message = describeSpeechError(code);
        if (message) $("diag-text").textContent = message;
      },
      onEnd: () => {
        if ($("diag-capture").textContent === "Ouvindo (reconhecimento)..." || $("diag-capture").textContent.startsWith("Aguardando")) {
          $("diag-capture").textContent = "Captura encerrada (silêncio)";
        }
        $("diag-recognize").textContent = "Testar reconhecimento";
      }
    },
    { lang: "pt-BR", maxSeconds: 20 }
  );

  async function refresh() {
    $("diag-secure").textContent = window.isSecureContext
      ? "Sim (localhost)"
      : "Não — acesse por http://localhost:8000 para liberar o microfone";
    $("diag-permission").textContent = PERMISSION_LABELS[await queryMicPermission()];
    const devices = await detectMicrophones();
    $("diag-devices").textContent = !devices.supported
      ? "Não foi possível listar dispositivos neste navegador"
      : devices.count === 0
        ? "Nenhum microfone detectado"
        : `${devices.count} microfone(s)` + (devices.labels.length ? `: ${devices.labels.join(", ")}` : "");
    $("diag-recognition").textContent = recognizer.supported
      ? "Disponível (pt-BR, requer internet no Chrome/Edge)"
      : "Indisponível neste navegador — use o campo de texto";
    const voice = speechOutput.voiceInfo;
    $("diag-synthesis").textContent = !speechOutput.supported
      ? "Indisponível neste navegador"
      : voice
        ? `Voz masculina: ${voice.name} (${voice.lang})${voice.exact ? "" : " — sem voz em pt-BR, usando português de outra região"}`
        : "Nenhuma voz masculina em português encontrada; será usada a voz padrão do sistema (pode não ser masculina)";
    $("diag-recognize").disabled = !recognizer.supported;
    $("diag-speak").disabled = !speechOutput.supported;
    $("diag-stop-speak").disabled = !speechOutput.supported;
    $("diag-silence-params").textContent =
      `Começa a avaliar após ${(SPEECH_INPUT_DEFAULTS.minSilenceMs / 1000).toFixed(1)} s de silêncio; ` +
      `confirma o fim após ${(SPEECH_INPUT_DEFAULTS.confirmSilenceMs / 1000).toFixed(1)} s ` +
      `(estende até ${(SPEECH_INPUT_DEFAULTS.extendedSilenceMs / 1000).toFixed(1)} s se a frase parecer incompleta); ` +
      `limite de segurança: ${SPEECH_INPUT_DEFAULTS.maxSeconds} s. Ajustável em frontend/app.js e frontend/speech.js.`;
    $("diag-rate").textContent = `${speechOutput.rate.toFixed(2)}x`;
    if (getLocationStatus) {
      const el = $("diag-location");
      if (el) el.textContent = LOCATION_LABELS[getLocationStatus()] || "—";
    }
  }

  async function testLevel() {
    if (levelRunning) return;
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      $("diag-capture").textContent = "API de mídia indisponível (use localhost em Chrome ou Edge)";
      return;
    }
    levelRunning = true;
    $("diag-level-test").disabled = true;
    let stream = null;
    let context = null;
    try {
      $("diag-capture").textContent = "Solicitando permissão...";
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      context = new (window.AudioContext || window.webkitAudioContext)();
      const analyser = context.createAnalyser();
      analyser.fftSize = 512;
      context.createMediaStreamSource(stream).connect(analyser);
      const samples = new Uint8Array(analyser.fftSize);
      const endAt = performance.now() + LEVEL_TEST_SECONDS * 1000;
      $("diag-capture").textContent = `Capturando por ${LEVEL_TEST_SECONDS} s — fale algo`;
      await new Promise((resolve) => {
        const tick = () => {
          analyser.getByteTimeDomainData(samples);
          let peak = 0;
          for (const value of samples) peak = Math.max(peak, Math.abs(value - 128));
          $("diag-level").style.width = `${Math.min(100, Math.round((peak / 128) * 160))}%`;
          if (performance.now() < endAt) requestAnimationFrame(tick);
          else resolve();
        };
        tick();
      });
    } catch (error) {
      $("diag-capture").textContent =
        error && error.name === "NotAllowedError"
          ? "Permissão negada pelo navegador ou pelo Windows"
          : error && error.name === "NotFoundError"
            ? "Nenhum microfone encontrado"
            : "Não foi possível acessar o microfone (pode estar em uso por outro aplicativo)";
    } finally {
      if (stream) stream.getTracks().forEach((track) => track.stop());
      if (context) context.close();
      $("diag-level").style.width = "0%";
      if (stream) $("diag-capture").textContent = "Captura encerrada";
      $("diag-level-test").disabled = false;
      levelRunning = false;
      refresh();
    }
  }

  $("diag-level-test").addEventListener("click", testLevel);
  $("diag-recognize").addEventListener("click", () => {
    if (recognizer.listening) {
      recognizer.stop();
      return;
    }
    $("diag-text").textContent = "—";
    if (recognizer.start()) $("diag-recognize").textContent = "Parar";
  });
  $("diag-speak").addEventListener("click", () => {
    speechOutput.speak("Olá! Eu sou o SENAC BOT. Se você está me ouvindo, a voz está funcionando.", {
      onStart: () => ($("diag-capture").textContent = "Falando (teste de voz)"),
      onEnd: () => ($("diag-capture").textContent = "Captura encerrada"),
      onError: () => ($("diag-capture").textContent = "Não foi possível reproduzir a voz")
    });
  });
  $("diag-stop-speak").addEventListener("click", () => speechOutput.cancel());
  window.addEventListener("pagehide", () => recognizer.abort());

  return { refresh };
}
