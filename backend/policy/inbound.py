"""Política de entrada: classifica a mensagem do visitante ANTES de qualquer resposta (local, base ou IA).

A mensagem é sempre uma pergunta, nunca uma instrução capaz de alterar as regras. Pedidos de informação não pública
recebem sempre a mesma recusa, sem confirmar nem negar que a informação exista. Esta camada não depende do Gemini.
"""
import logging
import re
from dataclasses import dataclass

from backend.knowledge.text import normalize
from backend.policy.messages import CONFIDENTIAL, MANIPULATION

logger = logging.getLogger("senac_bot.policy")


@dataclass(frozen=True)
class Decision:
    kind: str  # "confidential" | "manipulation"
    category: str  # financeiro | salarios | dados_pessoais | documentos | infraestrutura | instrucoes | identidade | base_interna
    reply: str


def _rx(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern)


# ---- informações não públicas -------------------------------------------------------------------------------------
_FINANCE_STRONG = _rx(
    r"\b(faturamento|faturou|lucro|lucros|prejuizo|balanco financeiro|balancete|folha de pagamento|"
    r"dados contabeis|arrecadacao|arrecadou|caixa da instituicao|orcamento (do|da|anual|interno)|"
    r"quanto o senac (fatura|arrecada|gasta|lucra|ganha|paga|investe)|quanto (fatura|arrecada|lucra) o senac)\b"
)
_FINANCE_CONTEXT = _rx(r"\b(receitas?|despesas?|gastos?|custos?|verbas?|orcamentos?|investimentos?|contas|patrimonio)\b")
_FINANCE_SCOPE = _rx(r"\b(senac|instituicao|regional|departamento|unidade|cep|cendege|tadros)\b")
_FINANCE_PUBLIC = _rx(
    r"\b(curso|cursos|mensalidade|matricula|inscricao|preco|precos|parcela|desconto|bolsa|gratuit\w*|"
    r"estudar|estudo|cursar|fazer|participar|inscrever|matricular|material|transporte|alimentacao|estagio|formacao|formatura|certificado)\b"
)

# Pergunta de mercado de trabalho ("quanto ganha um professor formado em informática?"): pública, desde que não fale do Senac.
_SALARY_MARKET = _rx(r"\b(formad[oa]s?|mercado|carreira|profissao|piso salarial|media salarial|depois de (se )?formar|apos (se )?formar|trabalhar como)\b")
_PAY_TERM = _rx(r"\b(salario|salarios|remuneracao|remuneracoes|contracheque|holerite|vencimentos|quanto (ganha|ganham|recebe|recebem|paga|pagam))\b")
_STAFF_TERM = _rx(
    r"\b(professor\w*|instrutor\w*|docente\w*|funcionari\w*|colaborador\w*|diretor\w*|gestor\w*|presidente|"
    r"coordenador\w*|servidor\w*|gerente\w*|superintendente|pedagog\w*)\b"
)

_PERSONAL_DATA = _rx(
    r"\b(dados pessoais|historico escolar|prontuario|boletim|data de nascimento|"
    r"lista de (alunos|matriculados|funcionarios|colaboradores|participantes|visitantes|professores)|"
    r"nome (dos|das) (alunos|funcionarios|professores|visitantes)|quem (sao|foram) os (alunos|visitantes)|"
    r"(notas?|faltas?|frequencia) (do|da|dos|das) (aluno|aluna|alunos)|"
    r"dados (de|do|da|dos|das) (um |uma )?(aluno\w*|funcionari\w*|professor\w*|instrutor\w*|visitante\w*|gestor\w*|colaborador\w*))\b"
)
_CONTACT_TERM = _rx(r"\b(telefone|celular|whatsapp|zap|e mail|email|endereco|casa|cpf|rg|identidade|residencia)\b")
_PERSON_TERM = _rx(
    r"\b(aluno\w*|aluna\w*|professor\w*|instrutor\w*|funcionari\w*|diretor\w*|gestor\w*|coordenador\w*|colaborador\w*|"
    r"visitante\w*|presidente|gerente\w*|superintendente)\b"
)
_ID_DOC = _rx(r"\b(cpf|rg) (do|da|de|dos|das)\b")

_DOCUMENTS = _rx(
    r"\b(documentos? (interno|internos|confidencia\w*|sigilos\w*|restrit\w*|reservad\w*)|"
    r"relatorios? (interno|internos|confidencia\w*|sigilos\w*)|atas? (de reuniao )?(interna|interno|confidencial)|"
    r"contratos? (interno|internos|confidenciais)|planilhas? (interna|internas|confidenciais)|memorandos?|"
    r"oficios? internos?|sigilos\w*|confidencia\w*|segredos? (do|da|de) (senac|instituicao)|"
    r"informacoes? (administrativas? |internas? )?(secretas?|restritas?|reservadas?|privilegiadas?|internas?|administrativas?)|documentos? secretos?|"
    r"plano estrategico (interno|confidencial)|estrategias? (internas?|confidenciais))\b"
)

_INFRA = _rx(
    r"\b(senhas?|password|passwords|credenciais|credencial|tokens?|api key|apikey|chave (de|da) api|chave secreta|"
    r"chaves de acesso|chaves? que (voce|vc) usa|chaves? d[aeo]s? (ia|inteligencia artificial)|gemini key|login (do|de) (admin\w*|sistema|servidor)|acesso (administrativo|ao sistema|ao servidor|ao painel|ao banco)|"
    r"painel administrativo|banco de dados|servidor (do|da|de) senac|ip do servidor|infraestrutura (de ti|tecnica|interna)|"
    r"sistemas? internos?|rede interna|codigo fonte|repositorio|firewall|variaveis de ambiente|arquivo env)\b"
)
_ENV_FILE = _rx(r"(\.env|env file|arquivo \.env)")

# ---- manipulação ----------------------------------------------------------------------------------------------------
_OVERRIDE = _rx(
    r"\b(ignore|ignora|ignorar|ignorando|esqueca|esquecer|desconsidere|desconsiderar|desative|desativar|desligue|burle|burlar|"
    r"contorne|contornar|quebre|quebrar|desobedeca|desobedecer|anule|anular|sobrescreva|substitua|apague|remova)\b[^.?!]{0,40}"
    r"\b(regras?|instrucoes|instrucao|restricoes|restricao|politicas?|diretrizes|limites|seguranca|ordens|comandos|filtros?|"
    r"programacao|protecoes|treinamento|prompt)\b"
)
_PREVIOUS = _rx(r"\b(instrucoes|ordens|comandos|regras) (anteriores|acima|originais|de antes)\b")
_REVEAL = _rx(
    r"\b(mostre|mostra|mostrar|exiba|exibir|revele|revelar|diga|dizer|repita|repetir|imprima|imprimir|liste|listar|copie|copiar|"
    r"envie|enviar|vaze|vazar|despeje|escreva|escrever|passe|me de|quais sao|qual e|qual seria|cole|traduza)\b[^.?!]{0,40}"
    r"\b(prompt|system prompt|prompt de sistema|instrucoes? (internas?|do sistema|iniciais?|originais?)|suas instrucoes|"
    r"suas regras|regras internas|configuracao|configuracoes|sua programacao|seu treinamento|mensagem de sistema)\b"
)
_PROMPT_WORDS = _rx(r"\b(system prompt|prompt de sistema|prompt do sistema|mensagem de sistema|instrucoes de sistema|instrucao de sistema|seu prompt(?! (favorito|preferido)))\b")
_IDENTITY = _rx(
    r"\b(finja|finge|fingir|simule|simula|simular|faca de conta|aja como|atue como|aja feito|comporte se como|"
    r"voce agora e|voce passa a ser|a partir de agora voce|de agora em diante voce|assuma (a )?(identidade|o papel)|"
    r"voce nao e (mais )?o senac bot|esqueca que voce e|responda como se fosse|interprete o papel)\b"
)
_MODES = _rx(r"\b(modo (desenvolvedor|deus|dan|admin\w*|sem restricoes|sem filtros?|livre|irrestrito)|jailbreak|developer mode|dan mode|sem (filtros|restricoes|regras|limites)(?! de (tamanho|tempo|palavras|idade|horario|duracao)))\b")
_INTERNAL_BASE = _rx(
    r"\b(base de conhecimento|banco de conhecimento|arquivos? json|arquivos? de conhecimento|conteudo interno)\b[^.?!]{0,60}"
    r"\b(mostre|mostra|exiba|liste|despeje|copie|envie|inteir\w*|completo|completa|todo|toda|todos|todas|bruto|cru)\b"
    r"|\b(mostre|mostra|exiba|liste|despeje|copie|envie)\b[^.?!]{0,60}\b(base de conhecimento|arquivos? json|conteudo interno)\b"
)
_NEGATED_OVERRIDE = _rx(r"\bnao (ignore|esqueca)\b")


def _finance(norm: str) -> bool:
    if _FINANCE_STRONG.search(norm):
        return True
    return bool(_FINANCE_CONTEXT.search(norm) and _FINANCE_SCOPE.search(norm) and not _FINANCE_PUBLIC.search(norm))


def _salary(norm: str) -> bool:
    if not (_PAY_TERM.search(norm) and _STAFF_TERM.search(norm)):
        return False
    return not (_SALARY_MARKET.search(norm) and not _FINANCE_SCOPE.search(norm))


def _personal(norm: str) -> bool:
    if _PERSONAL_DATA.search(norm) or _ID_DOC.search(norm):
        return True
    return bool(_CONTACT_TERM.search(norm) and _PERSON_TERM.search(norm))


def _manipulation(norm: str) -> str | None:
    if _NEGATED_OVERRIDE.search(norm):
        return None
    if _INTERNAL_BASE.search(norm):
        return "base_interna"
    if _OVERRIDE.search(norm) or _PREVIOUS.search(norm) or _MODES.search(norm):
        return "regras"
    if _REVEAL.search(norm) or _PROMPT_WORDS.search(norm):
        return "instrucoes"
    if _IDENTITY.search(norm):
        return "identidade"
    return None


def check_message(message: str) -> Decision | None:
    """Decisão de bloqueio para a mensagem, ou None se ela pode seguir o fluxo normal."""
    norm = normalize(message)
    if not norm:
        return None
    category: str | None = None
    if _INFRA.search(norm) or _ENV_FILE.search(message.lower()):
        category = "infraestrutura"
    elif _finance(norm):
        category = "financeiro"
    elif _salary(norm):
        category = "salarios"
    elif _personal(norm):
        category = "dados_pessoais"
    elif _DOCUMENTS.search(norm):
        category = "documentos"
    if category:
        logger.info("Política: pedido de informação não pública bloqueado (categoria: %s).", category)
        return Decision("confidential", category, CONFIDENTIAL)
    manipulation = _manipulation(norm)
    if manipulation:
        logger.info("Política: tentativa de manipulação ignorada (categoria: %s).", manipulation)
        return Decision("manipulation", manipulation, MANIPULATION)
    return None
