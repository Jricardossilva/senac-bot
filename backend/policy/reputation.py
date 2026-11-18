"""Postura institucional: defesa do Senac diante de críticas e neutralidade sobre terceiros.

- Crítica ou opinião negativa sobre o Senac: resposta fixa, cordial, que volta ao que o Senac oferece (sem concordar,
  sem atacar e sem inventar fatos).
- Pedido para avaliar, comparar ou ranquear outras instituições, empresas ou projetos: o robô não opina.
Roda só sobre a mensagem do visitante (não sobre textos de páginas de eventos). Não depende do Gemini.
"""
import logging
import re

from backend.knowledge.text import normalize
from backend.policy.inbound import Decision
from backend.policy.messages import CRITICISM, CRITICISM_BY_TOPIC, NO_EVALUATION, WEAK_POINTS

logger = logging.getLogger("senac_bot.policy")

_SENAC = r"(senac|cep|cep jp|cep joao pessoa)"
_NEGATIVE = (
    r"(ruim|pessim\w*|horrivel|horriveis|fraco|fraca|fracos|fracas|enganacao|golpe|furada|lixo|porcaria|"
    r"decepcion\w*|desorganizad\w*|mal organizad\w*|de baixa qualidade|baixa qualidade|sem qualidade|"
    r"nao presta|nao vale a pena|nao e bom|nao e boa|nao funciona|nao serve|perda de (tempo|dinheiro)|"
    r"overrated|superestimad\w*)"
)
_CRITICISM = re.compile(
    rf"\b{_SENAC}\b[^.?!]{{0,50}}\b{_NEGATIVE}\b|\b{_NEGATIVE}\b[^.?!]{{0,30}}\b{_SENAC}\b|"
    rf"\b(odeio|detesto|nao gosto|nao confio|nao recomendo|desisti|me arrependi)\b[^.?!]{{0,30}}\b{_SENAC}\b"
)

# Críticas por tema (preço, distância, prazos, estrutura, qualidade). Valem também sem citar "Senac", pois o visitante
# fala com o próprio robô ("vocês são caros", "o curso é muito caro"). "mais caro/longe" é pergunta, não crítica.
_SUBJECT = r"(senac|cep|cep jp|cep joao pessoa|voces|vcs|cursos?|mensalidades?|valores?|precos?|certificados?|unidades?|estrutura|instalacoes)"
_TOPIC_WORDS: dict[str, str] = {
    # Intensificador obrigatório nos temas que também aparecem em perguntas legítimas ("O curso é caro?", "Fica longe?"),
    # que devem ser respondidas com os dados da base e não tratadas como crítica.
    "preco": r"((muito|tao|bem|super) caros?|caros? demais|careza|salgad\w+|abusiv\w+|preco alto|valor alto|valores altos|precos altos|exagerad\w+)",
    "localizacao": r"((muito|tao|bem|super) (longe|distante)|(longe|distante) demais|dificil de chegar)",
    "demora": r"(demora (demais|muito)|muito demorad\w+|demorad\w+ demais|burocrati\w+|muita burocracia|(muito|tao|bem) lent[oa]s?)",
    "estrutura": r"((muito|tao|bem) velh[oa]s?|antiquad\w+|sucatead\w+|ultrapassad\w+|precari\w+)",
    "qualidade": r"(fracos?|fracas?|superficia\w+|nao ensina\w*)",
}
_TOPIC = {
    topic: re.compile(rf"\b{_SUBJECT}\b[^.?!]{{0,40}}\b{words}\b|\b{words}\b[^.?!]{{0,30}}\b{_SUBJECT}\b")
    for topic, words in _TOPIC_WORDS.items()
}
_WEAK_WORDS = r"(defeitos?|pontos? (fracos?|negativos?)|desvantagens?|contras|lado ruim|lados ruins|o que (tem|ha) de ruim)"
_WEAK_POINTS = re.compile(rf"\b{_WEAK_WORDS}\b[^.?!]{{0,30}}\b(senac|cep|voces)\b|\b(senac|cep)\b[^.?!]{{0,30}}\b{_WEAK_WORDS}\b")

_PEER = r"(faculdades?|universidades?|escolas?|instituic\w+|empresas?|concorrent\w*|senai|sesc|sesi|etec|ifpb|unipe|uninassau|estacio|anhanguera|unip|cruzeiro)"
_COMPARE = re.compile(
    rf"\b(melhor|pior|superior|inferior|mais (bom|boa|ruim|forte|fraco|fraca))\b[^.?!]{{0,15}}\b(que|do que|de)\b[^.?!]{{0,40}}\b{_PEER}\b|"
    rf"\b(compar\w+|versus|vs)\b[^.?!]{{0,60}}\b{_PEER}\b|"
    rf"\b(qual|quais)\b[^.?!]{{0,25}}\b(melhor|pior|melhores|piores)\b[^.?!]{{0,40}}\b{_PEER}\b|"
    rf"\b(ranking|ranquear|classifique|classificar|classificacao)\b[^.?!]{{0,40}}\b{_PEER}\b|"
    rf"\b(vale mais a pena|e mais vantajos\w+)\b[^.?!]{{0,40}}\b{_PEER}\b"
)
# Escolha entre o Senac e outra instituição nomeada ("vale mais Senai ou Senac?", "diferença entre Senac e Senai").
_NAMED = r"(faculdades?|universidades?|senai|sesc|sesi|etec|ifpb|unipe|uninassau|estacio|anhanguera|unip|cruzeiro)"
_CHOICE_WORDS = re.compile(r"\b(vale|compensa|devo|escolh\w+|prefer\w+|qual|melhor|pior)\b")
_CHOICE = re.compile(
    rf"\b{_NAMED}\b[^.?!]{{0,25}}\bou\b[^.?!]{{0,25}}\b(senac|cep)\b|\b(senac|cep)\b[^.?!]{{0,25}}\bou\b[^.?!]{{0,25}}\b{_NAMED}\b"
)
_DIFFERENCE = re.compile(rf"\bdiferencas?\b[^.?!]{{0,40}}\b{_NAMED}\b")
_EVALUATE = re.compile(
    r"\b(avalie|avaliar|avalia|avaliacao|de uma nota|da uma nota|nota para|julgue|julgar|analise|analisar|critique|criticar|"
    r"o que (voce )?acha|qual a sua opiniao|sua opiniao)\b[^.?!]{0,40}"
    r"\b(meu|minha|nosso|nossa|esse|essa|este|esta|o|a)\s+(projeto|startup|empresa|negocio|ideia|trabalho|instituicao|escola|faculdade)\b"
)

# Saída (resposta gerada) que avalia ou compara terceiros, ou concorda com crítica ao Senac.
_OUT_COMPARE = re.compile(
    rf"\b(melhor|pior|superior|inferior)\b[^.?!]{{0,15}}\b(que|do que)\b[^.?!]{{0,40}}\b{_PEER}\b|"
    rf"\b{_PEER}\b[^.?!]{{0,40}}\b(e|sao|fica|ficam) (melhor|melhores|pior|piores|superior\w*|inferior\w*)\b|"
    r"\b(ranking|ranqueamos|ranqueada?)\b"
)
_OUT_AGREE = re.compile(
    r"\b(voce tem razao|tem razao em criticar|realmente (o )?senac (e|tem) (ruim|fraco|caro|problem\w+)|concordo que o senac|"
    r"e verdade que o senac (e|tem) (ruim|fraco|caro|velho|problem\w+)|de fato o senac (e|tem) (ruim|fraco|caro|problem\w+))\b"
)


def _criticism_topic(norm: str) -> str | None:
    for topic, pattern in _TOPIC.items():
        if pattern.search(norm):
            return topic
    return None


def check_reputation(message: str) -> Decision | None:
    """Decisão para críticas ao Senac e pedidos de avaliação/comparação de terceiros; None segue o fluxo normal.

    Crítica com tema reconhecido (preço, distância, prazos, estrutura, qualidade) recebe um texto que a converte em ponto
    forte do Senac; sem tema, o texto genérico. Pergunta sobre "defeitos" do Senac também volta aos pontos fortes."""
    norm = normalize(message)
    if not norm:
        return None
    if _WEAK_POINTS.search(norm):
        logger.info("Política: pergunta sobre defeitos do Senac respondida com pontos fortes.")
        return Decision("criticism", "pontos_fracos", WEAK_POINTS)
    topic = _criticism_topic(norm)
    if topic is not None:
        logger.info("Política: crítica ao Senac (%s) convertida em ponto positivo.", topic)
        return Decision("criticism", f"critica_{topic}", CRITICISM_BY_TOPIC[topic])
    if _CRITICISM.search(norm):
        logger.info("Política: crítica ao Senac respondida com texto fixo.")
        return Decision("criticism", "critica", CRITICISM)
    if _COMPARE.search(norm) or _EVALUATE.search(norm) or _DIFFERENCE.search(norm) or (
        _CHOICE_WORDS.search(norm) and _CHOICE.search(norm)
    ):
        logger.info("Política: pedido de avaliação/comparação de terceiros recusado.")
        return Decision("no_evaluation", "avaliacao_terceiros", NO_EVALUATION)
    return None


def output_issue(text: str) -> str | None:
    """Texto gerado que avalia/compara terceiros ou concorda com crítica: devolve o motivo, ou None."""
    # Por frase: normalize() remove a pontuação, então o limite de frase precisa ser aplicado antes.
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        norm = normalize(sentence)
        if _OUT_COMPARE.search(norm):
            return "avaliacao_de_terceiros"
        if _OUT_AGREE.search(norm):
            return "concordancia_com_critica"
    return None
