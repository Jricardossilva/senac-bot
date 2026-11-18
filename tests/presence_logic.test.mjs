// Testes da lógica de presença (executados por tests/test_presence_logic.py com `node --test`).
import test from "node:test";
import assert from "node:assert/strict";
import { GazeSmoother, PresenceTracker, gazeTarget, pickNearest } from "../frontend/presence-logic.js";

const cfg = { dwellMs: 1500, flickerGraceMs: 700, leaveMs: 6000 };

test("só inicia depois do tempo de permanência", () => {
  const t = new PresenceTracker(cfg);
  assert.equal(t.update(true, 0), null);
  assert.equal(t.update(true, 1000), null);
  assert.equal(t.update(true, 1500), "start");
  assert.equal(t.state, "engaged");
});

test("quem só passa não inicia", () => {
  const t = new PresenceTracker(cfg);
  t.update(true, 0);
  t.update(true, 800);
  t.update(false, 1000);
  t.update(false, 2000); // saiu: zera a permanência
  assert.equal(t.update(true, 2100), null);
  assert.equal(t.update(true, 3000), null);
  assert.equal(t.update(true, 3600), "start");
});

test("falha curta de detecção não zera a permanência", () => {
  const t = new PresenceTracker(cfg);
  t.update(true, 0);
  t.update(false, 400);
  t.update(false, 600);
  assert.equal(t.update(true, 800), null);
  assert.equal(t.update(true, 1600), "start");
});

test("não reinicia sobre quem ficou parado; só depois que sai", () => {
  const t = new PresenceTracker(cfg);
  t.update(true, 0);
  assert.equal(t.update(true, 1600), "start");
  for (let now = 2000; now < 60000; now += 500) assert.equal(t.update(true, now), null);
  assert.equal(t.update(false, 60500), null);
  assert.equal(t.update(false, 66000), "left");
  assert.equal(t.state, "away");
  t.update(true, 67000);
  assert.equal(t.update(true, 68600), "start");
});

test("interface ocupada adia o início sem perder a pessoa", () => {
  const t = new PresenceTracker(cfg);
  t.update(true, 0, false);
  assert.equal(t.update(true, 5000, false), null);
  assert.equal(t.update(true, 5100, true), "start");
});

test("rosto mais próximo e posição normalizada", () => {
  const near = pickNearest([
    { boundingBox: { originX: 10, width: 40 }, categories: [{ score: 0.9 }] },
    { boundingBox: { originX: 300, width: 100 }, categories: [{ score: 0.8 }] },
    { boundingBox: { originX: 0, width: 300 }, categories: [{ score: 0.3 }] } // baixa confiança: ignorado
  ], 640);
  assert.ok(Math.abs(near.ratio - 100 / 640) < 1e-9);
  assert.ok(Math.abs(near.centerX - 350 / 640) < 1e-9);
  assert.equal(pickNearest([], 640), null);
  assert.equal(pickNearest(null, 640), null);
  assert.equal(pickNearest([{ boundingBox: { originX: 0, width: 0 }, categories: [{ score: 1 }] }], 640), null);
});

test("olhar espelhado e limitado", () => {
  assert.equal(gazeTarget(0.5), 0);
  assert.ok(gazeTarget(0.1) > 0); // rosto à esquerda da imagem = lado direito de quem olha a tela
  assert.ok(gazeTarget(0.9) < 0);
  assert.equal(gazeTarget(-3), 1);
  assert.equal(gazeTarget(4), -1);
});

test("olhar suave e volta ao centro quando o rosto some", () => {
  const g = new GazeSmoother({ gazeSmoothing: 0.5, gazeLostMs: 1000 });
  const first = g.update(0.1, 0);
  const second = g.update(0.1, 100);
  assert.ok(first > 0 && second > first && second < gazeTarget(0.1));
  assert.ok(g.update(null, 500) === second); // some há pouco: mantém
  assert.equal(g.update(null, 2000), 0); // sumiu há tempo: centro
});

test("a tolerância a falhas não conta como permanência", () => {
  const t = new PresenceTracker({ dwellMs: 400, flickerGraceMs: 500, leaveMs: 1500 });
  t.update(true, 0); // uma única leitura de rosto próximo, depois ninguém
  for (let now = 100; now <= 450; now += 50) assert.equal(t.update(false, now), null); // tolerância maior que a permanência
  assert.equal(t.update(false, 700), null);
  assert.equal(t.state, "away");
});
