"""Respostas locais (funcionam sem internet e sem Gemini)."""
import random
import re
from dataclasses import dataclass

from backend.knowledge import KnowledgeBase
from backend.knowledge.text import normalize as normalize  # noqa: PLC0414 (reexportado)

MAX_LOCAL_WORDS = 9  # mensagens longas são perguntas abertas: vão para o Gemini

FALLBACK_GENERIC = (
    "Essa pergunta eu ainda não sei responder por aqui, mas adoro conversar sobre robótica, "
    "tecnologia e inteligência artificial. Que tal perguntar: o que é robótica?"
)

# Variações para a mesma situação não soarem repetidas ao longo da conversa (o serviço alterna entre elas).
FALLBACK_VARIANTS = (
    FALLBACK_GENERIC,
    "Hmm, isso foge do que eu sei por enquanto. Posso falar sobre o Senac, seus cursos e unidades, ou sobre tecnologia e robótica. O que você prefere?",
    "Ainda não tenho uma resposta para isso. Que tal me perguntar sobre os cursos do Senac Paraíba, as unidades ou como funciona um robô?",
    "Essa eu não sei responder agora. Mas posso ajudar com cursos, unidades e programas do Senac, e com curiosidades de tecnologia. Qual desses te interessa?",
)
ACKNOWLEDGEMENTS = (
    "Certo! Se quiser saber mais sobre cursos, unidades ou tecnologia, é só perguntar.",
    "Tudo bem! Posso ajudar com outra dúvida sobre o Senac quando você quiser.",
    "Combinado! Sobre o que você gostaria de conversar agora?",
)
_ACK = re.compile(r"(sim|nao|ok|certo|entendi|tudo bem|beleza|uhum|aham|ta|ta bom|talvez|pode ser)( obrigado| obrigada)?")

GREETINGS = {
    "bom dia": "Bom dia! Eu sou o SENAC BOT. Pronto para descobrir algo novo sobre tecnologia hoje?",
    "boa tarde": "Boa tarde! Eu sou o SENAC BOT. Quer conversar sobre robôs, programação ou inteligência artificial?",
    "boa noite": "Boa noite! Eu sou o SENAC BOT. Ainda dá tempo de aprender algo legal sobre tecnologia. O que você quer saber?",
    "default": "Olá! Eu sou o SENAC BOT, seu parceiro de conversas sobre tecnologia. Sobre o que você tem curiosidade hoje?",
}

JOKES = [
    "Por que o programador confunde Natal com Halloween? Porque 31 de outubro é igual a 25 de dezembro, em octal! Quer outra?",
    "O que o robô disse para o parafuso? Você é mesmo uma peça-chave! Quer ouvir mais uma?",
    "Por que o computador ficou frio? Porque deixou a janela aberta! Gostou? Posso contar outra.",
]
QUESTIONS = [
    "Pergunta para você: que tarefa do seu dia a dia você gostaria que um robô fizesse? Me conte!",
    "Aqui vai uma: quais sentidos um robô precisa ter para andar sem bater nas coisas? Pense e me diga!",
    "Pergunta curiosa: você acha que a tecnologia deixa a vida mais simples ou mais complicada? Por quê?",
]
CHALLENGES = [
    "Desafio: pense em um robô que ajude em uma escola. Que sensores ele precisaria ter e o que faria? Me conte sua ideia!",
    "Desafio: descreva em passos simples como fazer um robô desviar de uma parede. Isso é um algoritmo!",
    "Desafio: o que um robô precisa para reconhecer que chegou à porta? Pense em sensores e me responda!",
]

@dataclass(frozen=True)
class KbText:
    """Texto que vem da base de conhecimento (fonte única); usa o fallback se a base não estiver disponível."""

    entry_id: str
    fallback: str
    suffix: str = ""


_RULES: tuple[tuple[str, "str | list[str] | KbText"], ...] = (
    (r"quem e (voce|vc|tu)|qual (e )?(o )?seu nome|como (voce|vc) se chama",
     "Eu sou o SENAC BOT, assistente virtual do Senac Paraíba: um robô educacional, curioso e apaixonado por tecnologia. Estou aqui para conversar e ajudar você a conhecer o Senac!"),
    (r"o que (voce|vc) faz|para que (voce|vc) serve|o que (voce|vc) sabe fazer",
     "Eu converso com os visitantes sobre tecnologia, robótica, programação e inteligência artificial, respondo por voz e simulo movimentos na tela. Pode perguntar!"),
    (r"o que e (o )?senac|quem e (o )?senac", KbText("br-senac-o-que-e", "O Senac é o Serviço Nacional de Aprendizagem Comercial, instituição de educação profissional voltada ao comércio de bens, serviços e turismo.")),
    (r"o que e (a )?robotica|me explique (a )?robotica", KbText("faq-robotica", "Robótica une mecânica, eletrônica e programação. Um robô percebe o ambiente com sensores, decide com um programa e age com motores.", " Legal, né?")),
    (r"o que e (a )?(inteligencia artificial|ia)|me explique (a )?(inteligencia artificial|ia)", KbText("faq-inteligencia-artificial", "Inteligência artificial é um tipo de software que identifica padrões e produz resultados. Um robô é uma máquina; ele pode usar IA, mas muitos robôs seguem só instruções programadas.")),
    (r"(voce|vc) e (um |uma )?(humano|humana|pessoa|gente|funcionario|funcionaria|atendente|pessoa de verdade|ser humano)( de verdade)?|tem alguem (ai|ai atras) falando",
     "Não, sou o assistente virtual do Senac, um robô. Não sou uma pessoa nem um funcionário, mas adoro ajudar com informações públicas sobre o Senac!"),
    (r"(voce|vc) e (um )?(robo|maquina)( de verdade)?",
     "Sim, sou um robô! Por enquanto, um robô virtual: existo na tela, converso e simulo movimentos. No futuro, poderei ganhar um corpo com peças LEGO."),
    (r"como (voce|vc) funciona|como funciona (o )?senac bot",
     "Você fala ou escreve e eu procuro uma resposta pronta. Se não tiver, posso consultar uma inteligência artificial online. Sem internet, uso só respostas locais. A IA nunca comanda meus motores."),
    (r"(me )?(conte|conta|diga) (uma )?piada|piada|quero uma piada", JOKES),
    (r"(me )?(faca|faz) (uma )?pergunta|(me )?pergunte (algo|alguma coisa)", QUESTIONS),
    (r"quero (um )?desafio|(me )?(de|da) (um )?desafio|desafio|me desafie", CHALLENGES),
    (r"(muito )?(obrigado|obrigada|valeu|brigado)( pela ajuda)?",
     "Por nada! Foi um prazer conversar com você. Se surgir outra curiosidade, é só chamar!"),
    (r"tchau|ate (logo|mais|breve)|adeus",
     "Tchau! Foi muito bom conversar com você. Continue curioso e volte sempre!"),
    (r"tudo bem( com (voce|vc))?|como (voce|vc) esta",
     "Tudo ótimo por aqui, ainda mais falando de tecnologia! E você, como está?"),
    (r"o que e (a )?tecnologia", KbText("faq-tecnologia", "Tecnologia é o uso de conhecimentos e ferramentas para resolver problemas e atender necessidades, de uma simples roda a um robô.")),
    (r"(me )?(conte|conta) (uma )?curiosidade|(uma )?curiosidade",
     "Uma curiosidade: alguns robôs usam sensores de distância para perceber obstáculos sem tocá-los, parecido com um morcego que usa ecos para se orientar!"),
)
_INTENTS = (
    "info", "info", "info", "info", "info", "info", "info", "info",
    "joke", "question", "challenge", "thanks", "farewell", "info", "info", "info",
)
assert len(_INTENTS) == len(_RULES)
_COMPILED = tuple(
    (re.compile(pattern), answer, intent)
    for (pattern, answer), intent in zip(_RULES, _INTENTS)
)
_GREETING_PREFIX = re.compile(r"(ola|oi|oie|opa|e ai|bom dia|boa tarde|boa noite)\b\s*")


@dataclass(frozen=True)
class LocalMatch:
    text: str
    intent: str  # greeting | info | joke | question | challenge | thanks | farewell


def _resolve(answer: "str | list[str] | KbText", knowledge: KnowledgeBase | None) -> str:
    if isinstance(answer, list):
        return random.choice(answer)
    if isinstance(answer, KbText):
        entry = knowledge.get(answer.entry_id) if knowledge else None
        return (entry.content if entry else answer.fallback) + answer.suffix
    return answer


def local_match(message: str, knowledge: KnowledgeBase | None = None) -> LocalMatch | None:
    """Resposta local para perguntas curtas e conhecidas; None se deve ir à base de conhecimento ou ao Gemini."""
    norm = normalize(message)
    if not norm or len(norm.split()) > MAX_LOCAL_WORDS:
        return None
    greeting = _GREETING_PREFIX.match(norm)
    rest = norm[greeting.end():].strip() if greeting else norm
    rest = re.sub(r"\s*(por favor|pf)$", "", rest)
    if greeting and not rest:
        return LocalMatch(GREETINGS.get(greeting.group(1), GREETINGS["default"]), "greeting")
    for pattern, answer, intent in _COMPILED:
        if pattern.fullmatch(rest):
            return LocalMatch(_resolve(answer, knowledge), intent)
    return None


def acknowledgement(message: str, turn: int = 0) -> str | None:
    """Confirmação solta ("sim", "não", "entendi") sem pergunta pendente: resposta curta e variada, em vez de erro."""
    if _ACK.fullmatch(normalize(message)):
        return ACKNOWLEDGEMENTS[turn % len(ACKNOWLEDGEMENTS)]
    return None


def local_answer(message: str, knowledge: KnowledgeBase | None = None) -> str | None:
    match = local_match(message, knowledge)
    return match.text if match else None


def contingency_answer(message: str, knowledge: KnowledgeBase | None = None) -> str:
    """Resposta quando o Gemini não pode ser usado: resposta da base, se houver, ou orientação geral."""
    if knowledge is not None:
        result = knowledge.search(message)
        if result.confident:
            return knowledge.answer_for(result)
    return FALLBACK_GENERIC
