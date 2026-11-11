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
from backend.policy.messages import CRITICISM, NO_EVALUATION

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

_PEER = r"(faculdades?|universidades?|escolas?|instituic\w+|empresas?|concorrent\w*|senai|sesc|sesi|etec|ifpb|unipe|uninassau|estacio|anhanguera|unip|cruzeiro)"
_COMPARE = re.compile(
    rf"\b(melhor|pior|superior|inferior|mais (bom|boa|ruim|forte|fraco|fraca))\b[^.?!]{{0,15}}\b(que|do que|de)\b[^.?!]{{0,40}}\b{_PEER}\b|"
    rf"\b(compar\w+|versus|vs)\b[^.?!]{{0,60}}\b{_PEER}\b|"
    rf"\b(qual|quais)\b[^.?!]{{0,25}}\b(melhor|pior|melhores|piores)\b[^.?!]{{0,40}}\b{_PEER}\b|"
    rf"\b(ranking|ranquear|classifique|classificar|classificacao)\b[^.?!]{{0,40}}\b{_PEER}\b|"
    rf"\b(vale mais a pena|e mais vantajos\w+)\b[^.?!]{{0,40}}\b{_PEER}\b"
)
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
_OUT_AGREE = re.compile(r"\b(voce tem razao|tem razao em criticar|realmente (o )?senac (e|tem) (ruim|fraco|problem\w+)|concordo que o senac)\b")


def check_reputation(message: str) -> Decision | None:
    """Decisão para críticas ao Senac e pedidos de avaliação/comparação de terceiros; None segue o fluxo normal."""
    norm = normalize(message)
    if not norm:
        return None
    if _CRITICISM.search(norm):
        logger.info("Política: crítica ao Senac respondida com texto fixo.")
        return Decision("criticism", "critica", CRITICISM)
    if _COMPARE.search(norm) or _EVALUATE.search(norm):
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
