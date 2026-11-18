// Lógica pura da presença (sem DOM, sem câmera, sem relógio próprio): decide quando um visitante "chegou" e quando "saiu",
// e para onde o avatar deve olhar. Só recebe números (rosto próximo ou não, posição horizontal) e o instante atual.
// Nenhuma imagem passa por aqui; quem detecta o rosto é presence.js, no navegador.

export const PRESENCE_DEFAULTS = Object.freeze({
  // Largura do rosto dividida pela largura da imagem. ~0,12 equivale a cerca de 1 m de uma webcam de notebook.
  nearRatio: 0.12,
  dwellMs: 1500, // tempo contínuo de rosto próximo antes de iniciar (evita quem apenas passa)
  flickerGraceMs: 700, // falha curta de detecção que não zera o tempo de permanência
  leaveMs: 6000, // tempo sem ninguém próximo para liberar um novo início (evita reiniciar sobre quem ficou parado)
  gazeGain: 3, // amplificação: o olhar chega ao limite quando o rosto se afasta ~17% da largura do centro da imagem
  gazeSmoothing: 0.5, // 0..1: quanto cada leitura nova pesa na posição do olhar
  gazeLostMs: 1500 // sem rosto por este tempo: o olhar volta ao centro
});

// Escolhe o rosto mais próximo (maior largura). `detections` no formato do MediaPipe: { boundingBox: { originX, width }, categories: [{ score }] }.
export function pickNearest(detections, frameWidth, minScore = 0.6) {
  if (!Array.isArray(detections) || !frameWidth) return null;
  let best = null;
  for (const detection of detections) {
    const box = detection && detection.boundingBox;
    const score = detection && detection.categories && detection.categories[0] ? detection.categories[0].score : 1;
    if (!box || !(box.width > 0) || score < minScore) continue;
    if (!best || box.width > best.width) best = { width: box.width, centerX: box.originX + box.width / 2 };
  }
  if (!best) return null;
  return { ratio: best.width / frameWidth, centerX: Math.min(1, Math.max(0, best.centerX / frameWidth)) };
}

// Posição do olhar entre -1 (esquerda da tela) e 1 (direita), a partir do centro do rosto na imagem da câmera (0..1).
// A imagem da câmera é espelhada em relação a quem está de frente para a tela, por isso o sinal invertido.
export function gazeTarget(centerX, gain = PRESENCE_DEFAULTS.gazeGain) {
  return Math.max(-1, Math.min(1, (0.5 - centerX) * 2 * gain));
}

export class PresenceTracker {
  #cfg;
  #state = "away"; // away: pronto para iniciar | engaged: já iniciou, aguardando a pessoa sair
  #nearSince = null;
  #lastNearAt = -Infinity;

  constructor(config = {}) {
    this.#cfg = { ...PRESENCE_DEFAULTS, ...config };
  }

  get state() {
    return this.#state;
  }

  get config() {
    return this.#cfg;
  }

  // `near`: há um rosto próximo agora. `canStart`: a interface está livre (sem conversa, demonstração ou emergência).
  // Devolve "start" no instante em que a conversa deve começar, "left" quando o visitante saiu, ou null.
  update(near, now, canStart = true) {
    if (near) {
      this.#lastNearAt = now;
      if (this.#nearSince === null) this.#nearSince = now;
    } else if (this.#nearSince !== null && now - this.#lastNearAt > this.#cfg.flickerGraceMs) {
      this.#nearSince = null;
    }
    if (this.#state === "away") {
      // O tempo conta só enquanto o rosto esteve de fato próximo (do primeiro ao último instante), não durante a tolerância.
      if (this.#nearSince !== null && this.#lastNearAt - this.#nearSince >= this.#cfg.dwellMs && canStart) {
        this.#state = "engaged";
        return "start";
      }
      return null;
    }
    if (!near && now - this.#lastNearAt >= this.#cfg.leaveMs) {
      this.#state = "away";
      this.#nearSince = null;
      return "left";
    }
    return null;
  }

  reset() {
    this.#state = "away";
    this.#nearSince = null;
    this.#lastNearAt = -Infinity;
  }
}

// Suaviza o olhar (média móvel exponencial) e o devolve ao centro quando o rosto some.
export class GazeSmoother {
  #value = 0;
  #lastSeenAt = -Infinity;
  #cfg;

  constructor(config = {}) {
    this.#cfg = { ...PRESENCE_DEFAULTS, ...config };
  }

  update(centerX, now) {
    if (centerX === null || centerX === undefined) {
      if (now - this.#lastSeenAt > this.#cfg.gazeLostMs) this.#value = 0;
      return this.#value;
    }
    this.#lastSeenAt = now;
    const target = gazeTarget(centerX, this.#cfg.gazeGain);
    this.#value += (target - this.#value) * this.#cfg.gazeSmoothing;
    return this.#value;
  }
}
