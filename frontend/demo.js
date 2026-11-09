// Roteiro do modo demonstração. As falas são locais (não dependem de internet nem do Gemini);
// só a etapa de perguntas usa o chat híbrido, que já tem contingência local.
// Todos os movimentos e expressões passam pelo controlador no backend (lista permitida + segurança).

export const DEMO_SCRIPT = [
  { name: "Cumprimentando", movement: "wave", say: "Olá! Seja muito bem-vindo à Robótica 2026!", expression: "happy" },
  {
    name: "Apresentando-se",
    say: "Eu sou o SENAC BOT, um robô educacional criado para o evento Robótica 2026 do Senac PB.",
    expression: "happy"
  },
  {
    name: "Explicando o que faço",
    say: "Eu converso com você sobre tecnologia, robótica, programação e inteligência artificial. Também respondo por voz e me movimento.",
    expression: "curious"
  },
  {
    name: "Oferecendo ajuda",
    say: "Como posso ajudar? Pode me perguntar o que quiser, falando ou digitando.",
    expression: "curious",
    questionsSeconds: 30
  },
  { name: "Propondo um desafio", chat: "Quero um desafio", expression: "curious" },
  {
    name: "Mostrando expressões",
    say: "Agora, veja algumas das minhas expressões.",
    expressions: ["happy", "curious", "surprised", "sad", "neutral"],
    gapMs: 1500
  },
  {
    name: "Mostrando movimentos",
    say: "E também sei me movimentar.",
    movements: [
      "look_left",
      "look_right",
      "tilt_head",
      "left_arm",
      "right_arm",
      "wave",
      "spin",
      "wheels_forward",
      "wheels_backward",
      "stop"
    ],
    gapMs: 2200
  },
  {
    name: "Despedindo-se",
    movement: "wave",
    say: "Foi um prazer receber você! Obrigado pela visita e volte sempre!",
    expression: "happy"
  }
];

const pause = (ms) => new Promise((resolve) => window.setTimeout(resolve, ms));

// ctx: { active(), setStep(name), command(action), say(text), chat(text), openQuestions(seconds) }
// command() nunca rejeita: movimentos bloqueados (obstáculo, desconexão) são ignorados e a demonstração continua.
export async function runDemo(ctx, script = DEMO_SCRIPT) {
  for (const step of script) {
    if (!ctx.active()) return "aborted";
    ctx.setStep(step.name);
    if (step.movement) await ctx.command(step.movement);
    if (step.say) await ctx.say(step.say);
    if (step.chat) await ctx.chat(step.chat);
    if (!ctx.active()) return "aborted";
    if (step.expression) await ctx.command(step.expression);
    for (const expression of step.expressions || []) {
      if (!ctx.active()) return "aborted";
      await ctx.command(expression);
      await pause(step.gapMs);
    }
    for (const movement of step.movements || []) {
      if (!ctx.active()) return "aborted";
      await ctx.command(movement);
      await pause(step.gapMs);
    }
    if (step.questionsSeconds) await ctx.openQuestions(step.questionsSeconds);
  }
  return ctx.active() ? "done" : "aborted";
}
