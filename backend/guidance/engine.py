"""Orientação para cursos: recomenda ofertas do Senac seguindo a prioridade institucional.

Prioridade obrigatória: 1) turmas abertas do CEP-JP; 2) turmas abertas das demais unidades do Senac Paraíba;
3) Senac EAD; 4) sem turma aberta: o visitante é orientado a procurar a unidade mais próxima.
As turmas vêm da última extração do portal oficial de matrículas (consulta diária feita ANTES, nunca durante a conversa),
com datas, horários, carga horária, valor e vagas falados junto da data da consulta. O catálogo (knowledge/offers.json)
cobre o que o portal não lista (cursos citados nas páginas oficiais e EAD). Nada vem da memória do modelo.
A busca começa sempre pelo CEP-JP, mas isso NÃO é dito ao visitante. O texto é montado aqui (determinístico e testável),
com uma recomendação por vez e uma pergunta para continuar.
"""
import logging
import re
from dataclasses import dataclass, field

from backend.guidance.session import GuidanceSessions, GuidanceState
from backend.knowledge import KnowledgeBase
from backend.knowledge.offers import Offer
from backend.knowledge.portal import DETAIL_QUESTION, PortalLookup, clean_segment, spoken_date
from backend.knowledge.text import contains_sequence, normalize, tokenize

logger = logging.getLogger("senac_bot.guidance")

COOLDOWN_MESSAGES = 3  # mínimo de mensagens entre uma recomendação espontânea e a próxima
MAX_ANSWER_WORDS_FOR_SUGGESTION = 50  # só acrescenta sugestão a respostas curtas (meta total: ~70 palavras)

LINK_LABELS = {
    "pb-programacao-cursos": "Programação de cursos do Senac Paraíba",
    "pb-tecnicos": "Cursos técnicos do Senac Paraíba",
    "pb-joao-pessoa": "Unidades do Senac em João Pessoa",
    "pb-unidades": "Unidades do Senac Paraíba",
    "br-cursos": "Cursos do Senac",
    "pb-psg": "Programa Senac de Gratuidade",
}

NO_PB_OFFER = "Não encontrei oferta confirmada para esse assunto nas unidades da Paraíba, então olhei a educação a distância."
NO_TURMA = "No momento não encontrei turma aberta desse assunto nas unidades do Senac Paraíba."
NO_TURMA_EAD = "No momento não encontrei turma aberta desse assunto nas unidades do Senac Paraíba, mas o Senac tem educação a distância."
NO_TURMA_OFFER = "Mas não encontrei turma aberta dele no momento."
ASK_OTHER = "Quer ver outra opção?"
NEAREST_PROMPT = "Procure a unidade do Senac mais próxima de você."
CONFIRM_UNIT = "A unidade que o oferece precisa ser confirmada na programação oficial."
CONFIRM_AVAILABILITY = "A disponibilidade atual precisa ser confirmada na programação oficial."
CONFIRM_EAD = "Os detalhes ficam na programação oficial."
STALE_NOTE = "Essa informação pode estar desatualizada."
ASK_MORE = "Quer conhecer mais detalhes?"
NO_DETAILS = "Não tenho confirmados preço, carga horária, datas, horários, vagas nem requisitos."
TURMA = "turma-"  # prefixo do id de uma turma do portal em state.recommended / offer_ids
DECLINE_ACK = "Tudo bem, não vou insistir nos cursos. Se mudar de ideia, é só pedir. Posso ajudar com outra dúvida sobre o Senac?"
NO_OTHER = "Por enquanto, essa é a única opção confirmada que tenho para esse interesse. Quer falar de outra área?"
ENTREPRENEUR = (
    "Que ótimo querer empreender! Não encontrei na minha base uma oferta confirmada sobre empreendedorismo. "
    "A programação oficial do Senac Paraíba, que deixei na tela, mostra os cursos atuais. Quer me contar outro interesse?"
)
UNMATCHED = (
    "Não encontrei na minha base uma oferta confirmada para esse assunto. "
    "O melhor caminho é ver a programação oficial do Senac Paraíba, que deixei na tela. Quer me contar outro interesse?"
)
UNMATCHED_PORTAL = f"{NO_TURMA} Quer me contar outro interesse?"
FREE_BASE = (
    "O Senac tem o Programa Senac de Gratuidade, mas nem todos os cursos são gratuitos: "
    "depende da programação, dos critérios e das condições de cada oferta."
)
FREE_SUBJECT = "Programa Senac de Gratuidade"
FREE_NO_STOCK = "Não tenho confirmadas as vagas gratuitas atuais."
FREE_ASK = "Qual curso ou área você procura? Posso indicar o que o Senac tem, e você confere se há oferta gratuita."

_CUE = re.compile(
    r"\b(quero|queria|gostaria|gosto|adoro|amo|tenho interesse|interesse|interessa|interessante|me interesso|pretendo|procuro|"
    r"procurando|preciso|trabalhar|trabalho com|estudar|aprender|carreira|profissao|formacao|capacitar|capacitacao|"
    r"qualificacao|qualificar|curso|cursos|sonho|vontade|pensando em|penso em|ha curso|existe curso|especializar)\b"
)
_INTEREST_VERB = re.compile(
    r"\b(quero|queria|gostaria|pretendo|procuro|procurando|tenho interesse|interesse|interessa|me interesso|sonho|vontade|pensando|penso|preciso)\b"
)
_COURSE_NOUN = re.compile(r"\b(curso|cursos|capacitacao|formacao|qualificacao|trabalhar com|trabalhar na area|estudar|aprender|conhecer|entender de|carreira|profissao|faculdade|graduacao)\b")
_GENERIC_COURSE = re.compile(
    r"(eu )?(quero|queria|gostaria de|preciso de|pretendo|procuro|estou procurando|tenho interesse em)( fazer| de| um| uma| algum| alguma| outro)*"
    r"( curso| cursos| capacitacao| formacao| qualificacao)( no senac| do senac| agora| ai| ainda)?( por favor)?"
    r"|(que|qual) curso (eu )?(devo|posso|deveria) fazer|qual curso (voce )?(recomenda|indica|sugere)|me (indique|recomende|sugira) (um )?curso"
)
_ENTREPRENEUR = re.compile(
    r"\b(abrir (uma |um |minha |meu )?(empresa|negocio|loja|firma)|empreender|empreendedorismo|empreendedor\w*|negocio proprio|"
    r"montar (um |uma |meu |minha )?(negocio|empresa|loja)|criar (uma |minha )?empresa)\b"
)
_LIST_QUESTION = re.compile(r"\b(quais|que) (sao os |sao as )?(cursos|tipos de cursos|areas)\b")
_DETAIL_TERMS = re.compile(
    r"\b(quanto custa|preco|precos|valor|valores|mensalidade|quanto e|quanto fica|horario|horarios|carga horaria|duracao|"
    r"quanto tempo|quando comeca|quando inicia|inicio|data|datas|vagas?|requisitos?|pre requisitos?|turno|turnos|prazo|prazos)\b"
)
_EAD = re.compile(r"\b(ead|ead|a distancia|distancia|curso online|cursos online|aulas online|ensino a distancia)\b")
_FREE = re.compile(r"\b(gratuit\w*|gratis|de graca|sem custo|nao pagar|bolsas?|isencao)\b")
_FREE_INFO = re.compile(
    r"\b(quem pode|quais (sao )?(os )?(criterios|requisitos)|como (funciona|participar|se inscrever|faco para participar)|"
    r"o que e|criterios|requisitos?|programa senac de gratuidade|psg)\b"
)
_DISINTEREST = re.compile(
    r"\b(nao (tenho|quero|me interessa|estou interessad\w*|preciso)|sem interesse|deixa pra la|deixa para la|"
    r"chega de|pare de falar|para de falar)\b"
)
_ABOUT_COURSES = re.compile(r"\b(curso|cursos|formacao|capacitacao|qualificacao|oferta|recomend\w*|sugest\w*|indicac\w*)\b")
_AFFIRM = re.compile(
    r"(sim|claro|quero|quero sim|pode|pode sim|pode ser|por favor|gostaria|gostaria sim|com certeza|manda|manda ver|fale mais|"
    r"me conte mais|conte mais|quero saber mais|quero mais detalhes|mais detalhes|detalhes|ok|beleza|bora|uhum|aham|isso|isso mesmo|"
    r"vamos|tenho interesse|tenho sim)( sim| por favor)?"
)
_NEGATIVE = re.compile(
    r"(nao|nao quero|nao obrigado|nao obrigada|nao precisa|agora nao|nao tenho interesse|nao por enquanto|por enquanto nao|"
    r"talvez depois|depois|deixa|deixa pra la|nao e isso)"
)
_ASKS = re.compile(r"^((o|a) )?(senac |voces |vcs )?(tem|tinha|existe|existem|ha|oferece|oferecem|quais|qual|onde|como|quando|quanto)\b")
_OTHER_OPTION = re.compile(r"\b(outra opcao|outras opcoes|outro curso|outros cursos|mais opcoes|alguma outra|tem outro|tem outra|outra alternativa)\b")


@dataclass(frozen=True)
class Link:
    label: str
    url: str


@dataclass(frozen=True)
class GuidanceReply:
    text: str
    links: tuple[Link, ...] = field(default_factory=tuple)
    offer_ids: tuple[str, ...] = field(default_factory=tuple)
    intent: str = "info"
    subject: str | None = None  # assunto da resposta, lembrado para perguntas curtas de acompanhamento


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:]




class Guidance:
    def __init__(self, knowledge: KnowledgeBase, sessions: GuidanceSessions | None = None, portal: PortalLookup | None = None) -> None:
        self._kb = knowledge
        self._portal = portal
        self._sessions = sessions or GuidanceSessions()
        self._offers = [o for o in knowledge.catalog.offers]
        self._keywords = {o.id: [tokenize(k) for k in o.keywords] for o in self._offers}
        self._refine = {o.id: [tokenize(k) for k in o.refine] for o in self._offers}
        self._areas = {a.id: [tokenize(k) for k in a.keywords] for a in knowledge.catalog.areas}

    @property
    def enabled(self) -> bool:
        return bool(self._offers)

    def clear(self) -> None:
        self._sessions.clear()

    # ------------------------------------------------------------------ consulta ao catálogo
    def _usable(self, offer: Offer) -> bool:
        return self._kb.effective_offer(offer) != "pending"

    def _match(self, text: str) -> list[tuple[Offer, int, int]]:
        """Ofertas compatíveis com o assunto: (oferta, pontos das palavras-chave, pontos de refinamento)."""
        tokens = tokenize(text)
        found = []
        for offer in self._offers:
            if not self._usable(offer):
                continue
            score = sum(len(k) for k in self._keywords[offer.id] if contains_sequence(tokens, k))
            if not score:
                continue
            refine = sum(len(k) for k in self._refine[offer.id] if contains_sequence(tokens, k))
            found.append((offer, score, refine))
        return found

    def _rank(self, text: str, exclude: set[str], ead_only: bool = False) -> list[Offer]:
        """Ordem obrigatória: CEP-JP, outras unidades do Senac PB, Senac EAD. A EAD só entra antes se o visitante pedir."""
        matches = [m for m in self._match(text) if m[0].id not in exclude]
        if ead_only:
            matches = [m for m in matches if m[0].tier == 3]
        else:
            non_ead = [m for m in matches if m[0].tier < 3]
            matches = non_ead or matches
        matches.sort(key=lambda m: (m[0].tier, -m[2], 1 if m[0].kind == "ead" else 0, -m[1], 0 if m[0].unit_known else 1, m[0].id))
        return [m[0] for m in matches]

    def _ead_fallback(self) -> Offer | None:
        return next((o for o in self._offers if o.kind == "ead" and self._usable(o)), None)

    def _links(self, offer: Offer | None = None) -> tuple[Link, ...]:
        ids = ["pb-programacao-cursos"]
        if offer is not None and offer.source_ids[0] not in ids:
            ids.append(offer.source_ids[0])
        out = []
        for source_id in ids:
            source = self._kb.sources.get(source_id)
            if source is not None:
                out.append(Link(LINK_LABELS.get(source_id, source.name), source.url))
        return tuple(out)

    def _confirm_note(self, offer: Offer) -> str:
        if offer.tier == 3:
            return CONFIRM_EAD
        return CONFIRM_AVAILABILITY if offer.unit_known else CONFIRM_UNIT

    def _stale_note(self, offer: Offer) -> str:
        return f" {STALE_NOTE}" if self._kb.effective_offer(offer) == "stale" else ""

    # ------------------------------------------------------------------ respostas da orientação
    def _recommend(self, state: GuidanceState, offer: Offer, opener: str | None = None, explicit_ead: bool = False) -> GuidanceReply:
        parts = [opener] if opener else []
        if offer.tier == 3 and not explicit_ead:
            parts.append(NO_PB_OFFER)  # prioridade 3: só chega à EAD quando não há oferta compatível nas unidades da Paraíba
        state.cep_checked = True
        parts += [offer.phrase, offer.pitch, self._confirm_note(offer) + self._stale_note(offer), ASK_MORE]
        self._remember(state, offer)
        return GuidanceReply(" ".join(parts), self._links(offer), (offer.id,))

    # ------------------------------------------------------------------ turmas do portal (prioridade: CEP-JP, outras unidades)
    def _portal_ready(self) -> bool:
        return self._portal is not None and self._portal.has_data()

    def _turmas(self, text: str, state: GuidanceState) -> list[dict]:
        return self._portal.find(text, frozenset(state.recommended)) if self._portal_ready() else []

    def _remember_turma(self, state: GuidanceState, turma: dict) -> str:
        tid = f"{TURMA}{turma['id']}"
        state.stage, state.last_offer_id, state.cep_checked, state.since_last = "more", tid, True, 0
        if tid not in state.recommended:
            state.recommended.append(tid)
        return tid

    def _recommend_turma(self, state: GuidanceState, turma: dict, opener: str | None = None) -> GuidanceReply:
        tid = self._remember_turma(state, turma)
        text = " ".join(p for p in (opener, self._portal.describe(turma), ASK_OTHER) if p)
        return GuidanceReply(text, self._links(), (tid,), subject=turma["curso"])

    def _related_turmas(self, state: GuidanceState, text: str) -> list[dict]:
        """Turmas abertas da ÁREA do assunto (ex.: tecnologia da informação) quando não há do assunto exato (ex.: programação)."""
        area = self._area_for(text) or next((a for a in self._kb.catalog.areas if a.id == state.area_id), None)
        if area is None or not area.segment or not self._portal_ready():
            return []
        state.area_id = area.id
        return self._portal.find_segment(area.segment, frozenset(state.recommended))

    def _no_turma(self, state: GuidanceState, text: str, opener: str | None = None) -> GuidanceReply | None:
        """Sem turma aberta do assunto exato: 1) turmas abertas da mesma ÁREA (CEP-JP primeiro); 2) EAD do assunto; 3) o curso
        citado nas páginas oficiais (sem turma) e a orientação de procurar a unidade mais próxima (o serviço acrescenta a unidade
        pela localização). None = nada do assunto."""
        related = self._related_turmas(state, text)
        if related:
            turma = related[0]
            self._remember_turma(state, turma)
            state.stage, state.topic_text = "details", text  # "sim" detalha esta turma; "outra opção" traz a próxima da área
            when = spoken_date(turma.get("inicio") or "")
            area = clean_segment(turma.get("segmento") or "") or "mesma área"
            start = f", com início em {when}" if when else ""
            body = f"{NO_TURMA} Na área de {_lower_first(area)}, a unidade {turma['unidade']} tem {turma['curso']}{start}. Quer saber mais?"
            return GuidanceReply(" ".join(p for p in (opener, body) if p), self._links(), (f"{TURMA}{turma['id']}",), subject=turma["curso"])
        ead = self._rank(text, set(state.recommended), True)
        if ead:
            return self._recommend(state, ead[0], " ".join(p for p in (opener, NO_TURMA_EAD) if p), explicit_ead=True)
        cited = self._rank(text, set(state.recommended))
        if not cited:
            return None
        state.cep_checked = True
        self._remember(state, cited[0])
        state.stage = None  # sem turma não há o que detalhar: a conversa segue livre
        return GuidanceReply(" ".join(p for p in (opener, cited[0].phrase, NO_TURMA_OFFER, NEAREST_PROMPT) if p), self._links(cited[0]), (cited[0].id,), intent="no_turma")

    def _recommend_for(self, state: GuidanceState, text: str, opener: str | None = None, ranked: list[Offer] | None = None) -> GuidanceReply | None:
        """Recomendação com a prioridade da instituição: turma aberta (CEP-JP, depois outras unidades), EAD, sem turma.
        Sem dados do portal (extração ausente), mantém o catálogo curado como antes."""
        if self._portal_ready():
            turmas = self._turmas(text, state)
            if turmas:
                return self._recommend_turma(state, turmas[0], opener)
            return self._no_turma(state, text, opener)
        ranked = ranked if ranked is not None else self._rank(text, set(state.recommended))
        return self._recommend(state, ranked[0], opener) if ranked else None

    def _details(self, state: GuidanceState, offer: Offer) -> GuidanceReply:
        note = "" if offer.unit_known or offer.tier == 3 else " Na programação, filtre pela unidade CEP João Pessoa para ver se há turma."
        state.stage = "more"
        text = f"{offer.phrase} {offer.pitch} {NO_DETAILS} Deixei os links oficiais na tela.{note}{self._stale_note(offer)} Quer ver outra opção?"
        return GuidanceReply(text, self._links(offer), (offer.id,))

    def _remember(self, state: GuidanceState, offer: Offer) -> None:
        state.stage = "details"
        state.last_offer_id = offer.id
        if offer.id not in state.recommended:
            state.recommended.append(offer.id)
        state.since_last = 0

    def _next_option(self, state: GuidanceState) -> GuidanceReply:
        if self._portal_ready():
            turmas = self._turmas(state.topic_text, state) or self._related_turmas(state, state.topic_text)
            if turmas:
                return self._recommend_turma(state, turmas[0], "Certo!")
            ead = self._rank(state.topic_text, set(state.recommended), True)
            if ead:
                return self._recommend(state, ead[0], "Certo!", explicit_ead=True)
            state.stage = None
            return GuidanceReply(NO_OTHER, self._links(), intent="no_match")
        candidates = self._rank(state.topic_text, set(state.recommended))
        if not candidates:
            state.stage = None
            return GuidanceReply(NO_OTHER, self._links(), intent="no_match")
        return self._recommend(state, candidates[0], "Certo!")

    def _decline(self, state: GuidanceState) -> GuidanceReply:
        state.declined = True
        state.stage = None
        return GuidanceReply(DECLINE_ACK)

    def _free(self, state: GuidanceState, message: str) -> GuidanceReply:
        psg = self._kb.get("program-psg")
        criteria = psg.short if psg and psg.short and self._kb.effective(psg) != "pending" else ""
        parts = [FREE_BASE] + ([criteria] if criteria else []) + [FREE_NO_STOCK]
        ranked = self._rank(message, set())
        links = list(self._links(ranked[0] if ranked else None))
        source = self._kb.sources.get("pb-psg")
        if source is not None:
            links.insert(0, Link(LINK_LABELS["pb-psg"], source.url))
        if ranked:
            offer = ranked[0]
            state.topic_text = message
            self._remember(state, offer)
            parts += [offer.phrase, "Quer saber mais?"]
            return GuidanceReply(" ".join(parts), tuple(links), (offer.id,), subject=FREE_SUBJECT)
        parts.append(FREE_ASK)
        return GuidanceReply(" ".join(parts), tuple(links), subject=FREE_SUBJECT)

    # ------------------------------------------------------------------ pontos de entrada
    def handle(self, session_id: str | None, message: str) -> GuidanceReply | None:
        """Resposta de orientação quando a mensagem pede/indica interesse em formação; None para seguir o fluxo normal."""
        if not self.enabled:
            return None
        norm = normalize(message)
        if not norm:
            return None
        state = self._sessions.get(session_id)
        state.since_last += 1

        followed = self._follow_up(state, norm, message)
        if followed is not None:
            return followed
        if _DISINTEREST.search(norm) and _ABOUT_COURSES.search(norm):
            return self._decline(state)
        if self._kb.detect_units(message):
            return None  # pergunta sobre uma unidade específica: a base responde sem misturar unidades
        if _ENTREPRENEUR.search(norm) and not self._rank(message, set()):
            state.declined = False
            return GuidanceReply(ENTREPRENEUR, self._links())
        if self._kb.search(message).corporate:
            return None  # empresa/equipe: a prioridade é o Senac Empresas (fluxo da base)

        free = bool(_FREE.search(norm))
        if free and not _FREE_INFO.search(norm) and (_CUE.search(norm) or re.search(r"\b(tem|existe|ha|existem|quais)\b", norm)):
            state.declined = False
            return self._free(state, message)

        ead_only = bool(_EAD.search(norm))
        ranked = self._rank(message, set(), ead_only)
        if ead_only and not ranked:
            fallback = self._ead_fallback()
            ranked = [fallback] if fallback else []
        turmas = [] if ead_only else self._turmas(message, state)  # turmas abertas do portal: sempre a primeira consulta
        topic = bool(ranked) or bool(turmas)

        if topic and _DETAIL_TERMS.search(norm):
            state.topic_text = message
            if turmas:  # perguntou preço/horário/vaga/data: fala os dados reais da turma, com a data da consulta
                return self._recommend_turma(state, turmas[0], "Sobre esse assunto:")
            if self._portal_ready() and not ead_only:
                reply = self._no_turma(state, message, "Sobre esse assunto:")
                if reply is not None:
                    return reply
            offer = ranked[0]
            self._remember(state, offer)
            text = f"Sobre esse assunto, {_lower_first(offer.phrase)} {NO_DETAILS} Deixei os links oficiais na tela. Quer que eu fale mais desse curso?"
            return GuidanceReply(text, self._links(offer), (offer.id,))

        if topic and _CUE.search(norm) and not _LIST_QUESTION.search(norm):
            state.declined = False  # pedido explícito do visitante reabre a orientação
            area = self._area_for(message)
            if area and not ead_only and area.id not in state.clarified_areas and not max((m[2] for m in self._match(message)), default=0):
                state.clarified_areas.add(area.id)
                state.stage, state.area_id, state.topic_text = "clarify", area.id, message
                opener = "Que legal!" if not state.greeted else "Certo!"
                state.greeted = True
                state.cep_checked = True
                text = f"{opener} {area.opener} O Senac tem formações para quem deseja atuar nessa área. {area.clarify}"
                return GuidanceReply(text, ())
            state.topic_text = message
            opener = "Que legal!" if not state.greeted and not _ASKS.search(norm) and not message.rstrip().endswith("?") else None  # pergunta não é "pedido empolgado"
            state.greeted = True
            if ead_only:
                return self._recommend(state, ranked[0], opener, ead_only)
            return self._recommend_for(state, message, opener, ranked)

        if not topic and not _DETAIL_TERMS.search(norm) and not _LIST_QUESTION.search(norm):
            if _GENERIC_COURSE.fullmatch(norm):
                state.declined = False
                state.stage, state.topic_text = "clarify", ""
                state.greeted = True
                return GuidanceReply(f"Que legal! {self._kb.catalog.generic_prompt}", self._links())
            if _INTEREST_VERB.search(norm) and _COURSE_NOUN.search(norm):
                state.declined = False
                if self._portal_ready():  # a programação (portal) foi consultada e não há turma aberta desse assunto
                    return GuidanceReply(UNMATCHED_PORTAL, self._links(), intent="no_turma")
                # Sem dados do portal: antes de desistir, o chamador pode consultar o cache do portal oficial.
                return GuidanceReply(UNMATCHED, self._links(), intent="no_match")
        return None

    def _area_for(self, message: str):
        tokens = tokenize(message)
        for area in self._kb.catalog.areas:
            if any(contains_sequence(tokens, k) for k in self._areas[area.id]):
                return area
        return None

    def _follow_up(self, state: GuidanceState, norm: str, message: str) -> GuidanceReply | None:
        stage = state.stage
        if stage is None:
            return None
        words = norm.split()
        if stage == "clarify":
            state.stage = None
            if _DISINTEREST.search(norm) or (len(words) <= 4 and _NEGATIVE.fullmatch(norm)):
                return self._decline(state)
            combined = f"{state.topic_text} {message}"
            if not self._portal_ready() and not self._rank(combined, set(state.recommended)):
                return None
            reply = self._recommend_for(state, combined, "Certo!")
            if reply is not None:
                state.topic_text = combined
            return reply
        if (state.last_offer_id or "").startswith(TURMA):
            return self._follow_up_turma(state, norm, words)
        offer = next((o for o in self._offers if o.id == state.last_offer_id), None)
        if offer is None:
            state.stage = None
            return None
        if len(words) <= 6 and _NEGATIVE.fullmatch(norm):
            return self._decline(state)
        if _OTHER_OPTION.search(norm):
            return self._next_option(state)
        if len(words) <= 6 and _AFFIRM.fullmatch(norm):
            return self._details(state, offer) if stage == "details" else self._next_option(state)
        state.stage = None  # a conversa seguiu outro rumo
        return None

    def _follow_up_turma(self, state: GuidanceState, norm: str, words: list[str]) -> GuidanceReply | None:
        """Depois de recomendar uma turma do portal: 'não' encerra; 'sim'/'outra opção' traz a próxima turma;
        pergunta curta de valor/horário/vaga/data repete os dados da turma (todos já foram falados na recomendação)."""
        if len(words) <= 6 and _NEGATIVE.fullmatch(norm):
            return self._decline(state)
        if state.stage == "details" and len(words) <= 6 and _AFFIRM.fullmatch(norm) and self._portal is not None:
            turma = self._portal.get_turma(state.last_offer_id or "")  # sugestão curta aceita: agora com todos os dados
            if turma is not None:
                state.stage = "more"
                return GuidanceReply(f"{self._portal.describe(turma)} {ASK_OTHER}", self._links(), (state.last_offer_id,))
        if _OTHER_OPTION.search(norm) or (len(words) <= 6 and _AFFIRM.fullmatch(norm)):
            return self._next_option(state)
        if len(words) <= 8 and DETAIL_QUESTION.search(norm) and self._portal is not None:
            turma = self._portal.get_turma(state.last_offer_id or "")
            if turma is not None:
                return GuidanceReply(f"{self._portal.describe(turma)} {ASK_OTHER}", self._links(), (state.last_offer_id,))
        state.stage = None  # a conversa seguiu outro rumo
        return None

    def suggestion(self, session_id: str | None, message: str, answer: str, topic_hint: str = "", hint_first: bool = False) -> GuidanceReply | None:
        """Sugestão educacional curta para concluir uma resposta sobre outro assunto (sem forçar nem repetir)."""
        if not self.enabled or len(answer.split()) > MAX_ANSWER_WORDS_FOR_SUGGESTION:
            return None
        state = self._sessions.get(session_id)
        if state.declined or state.since_last < COOLDOWN_MESSAGES or state.stage in ("clarify", "details", "more"):
            return None
        norm = normalize(message)
        if _DISINTEREST.search(norm) or self._kb.detect_units(message):
            return None
        if self._portal_ready() and not _EAD.search(norm):
            # Sugestão só com turma aberta de verdade (CEP-JP primeiro); o tema do evento é a pista quando a pergunta não tem assunto.
            for candidate in ([topic_hint, message] if hint_first and topic_hint else [message, topic_hint]):
                turmas = self._turmas(candidate, state) if candidate else []
                if turmas:
                    turma = turmas[0]
                    self._remember_turma(state, turma)
                    state.stage, state.topic_text = "details", candidate
                    start = spoken_date(turma.get("inicio") or "")
                    when = f", com início em {start}" if start else ""
                    return GuidanceReply(f"Aliás, a unidade {turma['unidade']} tem turma de {turma['curso']}{when}. Quer saber mais?",
                                         self._links(), (f"{TURMA}{turma['id']}",))
        ranked, topic = [], message
        if hint_first and topic_hint:  # resposta sobre o evento: o tema do evento orienta a sugestão (não palavras soltas da pergunta)
            ranked, topic = self._rank(topic_hint, set(state.recommended)), topic_hint
        if not ranked:
            ranked, topic = self._rank(message, set(state.recommended), bool(_EAD.search(norm))), message
        if not ranked and topic_hint:  # evento ativo: o tema do evento é a pista quando a pergunta não tem assunto próprio
            ranked, topic = self._rank(topic_hint, set(state.recommended)), topic_hint
        if not ranked:
            return None
        offer = ranked[0]
        state.topic_text = topic
        self._remember(state, offer)
        return GuidanceReply(f"Aliás, {_lower_first(offer.phrase)} Quer saber mais?", self._links(offer), (offer.id,))
