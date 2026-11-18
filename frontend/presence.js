// Câmera de presença: detecta se há um rosto próximo, SEM identificar ninguém e SEM gravar ou enviar imagem.
// Tudo roda neste navegador (MediaPipe Face Detector, arquivos em /assets/vendor/mediapipe, sem internet). Cada quadro é
// analisado e descartado; só saem dois números por leitura (tamanho e posição do rosto). Nada de reconhecimento facial.
import { pickNearest } from "/assets/presence-logic.js";

const VENDOR = "/assets/vendor/mediapipe";

export class PresenceCamera {
  #onSample;
  #onStatus;
  #intervalMs;
  #minScore;
  #status = "off"; // off | starting | on | denied | no-device | error
  #stream = null;
  #video = null;
  #detector = null;
  #timer = null;
  #run = 0;

  constructor({ onSample, onStatus, intervalMs = 200, minScore = 0.6 }) {
    this.#onSample = onSample;
    this.#onStatus = onStatus;
    this.#intervalMs = intervalMs;
    this.#minScore = minScore;
  }

  get status() {
    return this.#status;
  }

  static get supported() {
    return Boolean(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
  }

  #setStatus(status) {
    this.#status = status;
    this.#onStatus?.(status);
  }

  async start() {
    if (this.#status === "on" || this.#status === "starting") return this.#status === "on";
    if (!PresenceCamera.supported) {
      this.#setStatus("error");
      return false;
    }
    const run = ++this.#run;
    this.#setStatus("starting");
    try {
      this.#stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: "user" },
        audio: false
      });
    } catch (error) {
      this.#setStatus(error && error.name === "NotFoundError" ? "no-device" : error && error.name === "NotAllowedError" ? "denied" : "error");
      return false;
    }
    if (run !== this.#run) {
      this.#release();
      return false;
    }
    try {
      if (!this.#detector) {
        const vision = await import(`${VENDOR}/vision_bundle.mjs`);
        const fileset = await vision.FilesetResolver.forVisionTasks(VENDOR);
        this.#detector = await vision.FaceDetector.createFromOptions(fileset, {
          baseOptions: { modelAssetPath: `${VENDOR}/blaze_face_short_range.tflite`, delegate: "CPU" },
          runningMode: "VIDEO",
          minDetectionConfidence: this.#minScore
        });
      }
      const video = document.createElement("video");
      video.muted = true;
      video.playsInline = true;
      video.setAttribute("aria-hidden", "true");
      video.style.cssText = "position:fixed;left:-9999px;width:2px;height:2px;opacity:0;pointer-events:none";
      video.srcObject = this.#stream;
      document.body.append(video);
      await video.play();
      if (run !== this.#run) {
        video.remove();
        this.#release();
        return false;
      }
      this.#video = video;
    } catch {
      this.#release();
      this.#setStatus("error");
      return false;
    }
    this.#setStatus("on");
    this.#schedule(run);
    return true;
  }

  #schedule(run) {
    this.#timer = window.setTimeout(() => this.#tick(run), this.#intervalMs);
  }

  #tick(run) {
    if (run !== this.#run || !this.#video || !this.#detector) return;
    try {
      if (this.#video.readyState >= 2 && this.#video.videoWidth > 0) {
        const result = this.#detector.detectForVideo(this.#video, performance.now());
        this.#onSample(pickNearest(result.detections, this.#video.videoWidth, this.#minScore), performance.now());
      }
    } catch {
      // um quadro com falha é ignorado; falhas seguidas aparecem como "sem rosto"
    }
    this.#schedule(run);
  }

  #release() {
    if (this.#stream) this.#stream.getTracks().forEach((track) => track.stop());
    this.#stream = null;
    if (this.#video) {
      this.#video.srcObject = null;
      this.#video.remove();
    }
    this.#video = null;
  }

  // Desliga a câmera (a luz do aparelho apaga) e descarta qualquer quadro em andamento.
  stop() {
    this.#run += 1;
    window.clearTimeout(this.#timer);
    this.#release();
    if (this.#status !== "off") this.#setStatus("off");
  }
}
