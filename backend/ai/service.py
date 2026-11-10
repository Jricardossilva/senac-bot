"""Serviço de chat híbrido com política institucional.

Ordem: política de entrada -> respostas locais curtas -> orientação de cursos -> base de conhecimento -> Gemini -> contingência.
Toda resposta, de qualquer origem, passa pela política de saída antes de sair (sem vazar instruções, credenciais ou
dados pessoais; sem se dizer humana; sem prometer vagas; gratuidade sempre com ressalva; texto falável).

Perguntas institucionais SEMPRE consultam a base antes de qualquer resposta:
 - com dados confiáveis: o Gemini (se disponível) só organiza e explica esses dados; a resposta é descartada se
   trouxer números que não estão nos dados; sem Gemini, responde-se direto com o texto da base;
 - sem dados: informa que não há confirmação e indica o canal oficial (nunca inventa nem presume).
"""
import logging
import re
import time
from collections import OrderedDict
from dataclasses import dataclass, field, replace
from typing import Literal

from backend.ai.base import AIError, AIProvider, SearchAnswer
from backend.ai.context import SessionContexts
from backend.ai.local_answers import (
    FALLBACK_GENERIC,
    FALLBACK_VARIANTS,
    acknowledgement,
    contingency_answer,
    local_match,
)
from backend.ai.persona import KNOWLEDGE_RULES, SYSTEM_INSTRUCTION
from backend.eventkb import EventManager, event_prompt_block
from backend.guidance import Guidance, Link
from backend.knowledge import KnowledgeBase
from backend.knowledge.compose import ungrounded_numbers
from backend.knowledge.portal import PortalLookup
from backend.knowledge.text import contains_sequence, normalize, tokenize
from backend.policy import OutboundPolicy, check_message

logger = logging.getLogger("senac_bot.chat")

Source = Literal["local", "gemini", "fallback", "knowledge", "policy", "guidance", "event", "external", "portal"]

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_LONG_NUMBER = re.compile(r"(?:\+?\d[\s().-]?){8,}")

_STATUS_BY_ERROR = {
    "invalid_key": "invalid_key",
    "rate_limited": "rate_limited",
    "model_unavailable": "model_unavailable",
    "unavailable": "unavailable",
}

_FREE_TOPIC = re.compile(r"\b(gratuit\w*|gratis|de graca|sem custo|bolsas?)\b")
# Pergunta curta de acompanhamento ("E o telefone?", "Quem pode fazer?"): usa a unidade/assunto da conversa atual.
_FOLLOW_UP = re.compile(r"^(e|mas|entao|tambem|ainda|alem disso)\b|^(quem pode|como (faz|faco|funciona|chego)|quanto|quando|onde|qual (e )?o|quais( sao)? os)\b")
_DEICTIC = re.compile(r"\b(la|ali|nela|dela|nessa unidade|nesta unidade|dessa unidade|desta unidade)\b")
# Pedido de dado variável de turma (preço, horário, vaga...): a base não tem; o robô diz isso em vez de responder com outro assunto.
_VOLATILE_DATA = re.compile(
    r"\b(precos?|quanto custa|mensalidade|horarios?|carga horaria|vagas?|quando (comeca|inicia|abre)|datas? de (inicio|matricula|inscricao)|"
    r"datas? das turmas|turnos?|duracao do curso|proxima turma)\b"
)
_NOT_ABOUT_COURSES = re.compile(r"\b(emprego|trabalho|oportunidades?)\b")
# Pergunta por proximidade geográfica: calculada em Python (Haversine), nunca pelo Gemini (ver backend/knowledge/geo.py).
_NEAREST_UNIT = re.compile(
    r"(unidade|senac|cep)\w*[\w\s]{0,30}(mais proxim\w*|mais perto|mais pertinho|perto|proxim\w*)"
    r"|perto de mim\b|proxim\w* de mim\b|perto daqui\b|proxim\w* daqui\b|aqui perto\b"
    r"|como (chego|chegar|cheg\w*)[\w\s]{0,20}(unidade|senac)[\w\s]{0,20}proxim\w*"
    r"|qual[\w\s]{0,10}unidade[\w\s]{0,15}proxim\w*"
)
_WANTS_COURSES = re.compile(r"\b(curso|cursos|formacao|capacitacao|qualificacao|matricula|matricular)\b")
EXTERNAL_CACHE_SECONDS = 600
EXTERNAL_MIN_GAP_SECONDS = 2.0
EXTERNAL_MAX_WORDS = 55
EXTERNAL_HEDGE = "Essa informação veio de uma pesquisa na internet e não foi confirmada pela organização do evento."
MAX_FOLLOW_UP_WORDS = 6
MAX_SUBJECT_SESSIONS = 50
SUBJECT_CATEGORIES = ("programs", "units", "social", "empresas", "courses")


@dataclass
class _Subject:
    unit_alias: str | None = None
    hint: str | None = None


CORPORATE_ASK = "Você procura treinamento para sua empresa ou gostaria de conhecer melhor essas soluções?"
SOCIAL_ASK = "Quer conhecer mais sobre as ações educativas, a educação ambiental ou a inclusão profissional?"
MAX_WORDS_WITH_FOLLOW_UP = 80


def redact_personal_data(text: str) -> str:
    """Remove e-mails e números longos (telefone, CPF etc.) antes de enviar ao Gemini."""
    return _LONG_NUMBER.sub("[removido]", _EMAIL.sub("[removido]", text))


@dataclass(frozen=True)
class ChatReply:
    text: str
    source: Source
    reason: str | None = None
    intent: str | None = None
    knowledge: tuple[str, ...] = field(default_factory=tuple)  # ids das entradas/ofertas usadas (uso do operador)
    links: tuple[Link, ...] = field(default_factory=tuple)  # links oficiais mostrados na interface (nunca falados)
    follow_up: str | None = None  # pergunta de continuidade a acrescentar se a resposta ainda não tiver uma


class ChatService:
    def __init__(
        self,
        provider: AIProvider,
        contexts: SessionContexts | None = None,
        knowledge: KnowledgeBase | None = None,
        secrets: tuple[str, ...] = (),
        protected_texts: tuple[str, ...] | None = None,
        events: EventManager | None = None,
        external_search: bool = True,
        portal: PortalLookup | None = None,
    ) -> None:
        self._portal = portal
        self._events = events
        self._external_enabled = external_search
        self._external_cache: OrderedDict[str, tuple[float, ChatReply | None]] = OrderedDict()
        self._external_last = 0.0
        self._provider = provider
        self._contexts = contexts or SessionContexts()
        self._knowledge = knowledge
        self._status = "configured" if provider.is_configured() else "not_configured"
        self._guidance = Guidance(knowledge, portal=portal) if knowledge is not None else None
        self._subjects: OrderedDict[str, _Subject] = OrderedDict()  # assunto da conversa atual (só em memória)
        self._variants: dict[str, int] = {}  # quantas vezes cada tipo de resposta padrão já foi usado na sessão
        emails, numbers = knowledge.public_contact_data() if knowledge is not None else (frozenset(), frozenset())
        self._policy = OutboundPolicy(
            protected_texts if protected_texts is not None else (SYSTEM_INSTRUCTION, KNOWLEDGE_RULES),
            secrets, emails, numbers,
            contacts=self._extra_contacts if (events is not None or portal is not None) else None,
        )

    def _extra_contacts(self) -> tuple[frozenset[str], frozenset[str]]:
        """Contatos públicos que não vêm da base curada: do evento ativo e do portal oficial de matrículas
        (mesma fonte oficial do Senac PB, por outro canal) — sem isso, a política de saída trataria telefone
        e CEP reais das unidades, citados ao informar local e contato, como vazamento de dado pessoal."""
        emails, numbers = self._events.active().contacts() if self._events and self._events.active() else (frozenset(), frozenset())
        if self._portal is not None:
            numbers = numbers | self._portal.public_numbers()
        return emails, numbers

    @property
    def knowledge(self) -> KnowledgeBase | None:
        return self._knowledge

    @property
    def ai_status(self) -> str:
        """not_configured | configured | available | invalid_key | rate_limited | unavailable | model_unavailable"""
        return self._status

    def _record_error(self, error: AIError) -> None:
        # Resposta vazia/bloqueada não indica que a API caiu.
        if error.kind in _STATUS_BY_ERROR:
            self._status = _STATUS_BY_ERROR[error.kind]

    def check_ai(self) -> str:
        if not self._provider.is_configured():
            self._status = "not_configured"
            return self._status
        try:
            self._provider.check_availability()
            self._status = "available"
        except AIError as error:
            self._record_error(error)
        return self._status

    def clear_contexts(self) -> None:
        self._contexts.clear()
        if self._guidance is not None:
            self._guidance.clear()
        self._subjects.clear()
        self._variants.clear()

    # ------------------------------------------------------------------ resposta
    def reply(self, session_id: str | None, message: str, lat: float | None = None, lon: float | None = None) -> ChatReply:
        # 1) Política de entrada: a mensagem é uma pergunta, nunca uma instrução. Não entra no histórico do Gemini.
        decision = check_message(message)
        if decision is not None:
            return ChatReply(decision.reply, "policy", decision.category, "policy")

        routed = self._route(session_id, message, lat, lon)
        # 2) Política de saída em TODAS as respostas.
        final = self._vary(session_id, self._finish(session_id, message, routed))
        self._contexts.add_exchange(session_id, redact_personal_data(message), final.text)
        return final

    def _route(self, session_id: str | None, message: str, lat: float | None = None, lon: float | None = None) -> ChatReply:
        local = local_match(message, self._knowledge)
        if local is not None:
            return ChatReply(local.text, "local", intent=local.intent)

        active = self._events.active() if self._events is not None else None
        if active is not None and not active.empty:
            event_reply = self._answer_event(session_id, message, redact_personal_data(message), active)
            if event_reply is not None:
                return event_reply

        nearest_reply = self._nearest_unit_reply(message, lat, lon)
        if nearest_reply is not None:
            return nearest_reply

        if self._guidance is not None:
            guided = self._guidance.handle(session_id, self._with_unit(session_id, message))
            if guided is not None:
                portal_override = None
                if guided.intent == "no_turma":
                    # Sem turma aberta do assunto (portal consultado antes): orienta a procurar a unidade mais próxima.
                    near = self._nearest_hint(message, lat, lon)
                    return ChatReply(f"{guided.text} {near}", "guidance", None, "info", guided.offer_ids, guided.links)
                if guided.intent == "no_match":
                    # A orientação não achou nada no catálogo curado: antes de desistir, tenta o cache do
                    # portal oficial de matrículas (dados reais de turmas, atualizados automaticamente).
                    portal_override = self._portal_text_reply(message)
                else:
                    portal_override = self._cep_jp_priority_reply(message, guided)
                if portal_override is not None:
                    return portal_override
                if guided.subject:
                    self._remember(session_id, hint=guided.subject)
                return ChatReply(guided.text, "guidance", None, guided.intent, guided.offer_ids, guided.links)

        ack = acknowledgement(message, self._turn(session_id, "ack"))
        if ack is not None:
            return ChatReply(ack, "local", intent="info")

        safe_message = redact_personal_data(message)
        if self._knowledge is not None:
            result = self._knowledge.search(self._contextual_query(session_id, self._with_unit(session_id, message)))
            if _VOLATILE_DATA.search(normalize(message)) and not _NOT_ABOUT_COURSES.search(normalize(message)) and "faq-valores-vagas-datas" not in result.ids[:1]:
                entry = self._knowledge.get("faq-valores-vagas-datas")
                if entry is not None:  # a própria entrada diz que o dado não está confirmado (status pending)
                    return ChatReply(entry.content, "knowledge", "volatile_data", "info", (entry.id,))
            portal_reply = self._portal_reply(message, result)
            if portal_reply is not None:
                return portal_reply
            if result.hits and result.confident:
                self._remember_result(session_id, result)
                return self._answer_with_knowledge(session_id, message, safe_message, result)
            if active is not None and active.mentions_event(message):
                return self._event_without_data(message, safe_message, active)
            if result.institutional:
                # Pergunta sobre o Senac sem dados confiáveis na base: não inventar, não presumir.
                return ChatReply(self._knowledge.no_confirmation(), "knowledge", "no_match", "info")

        if active is not None and active.mentions_event(message):
            return self._event_without_data(message, safe_message, active)
        return self._answer_general(session_id, message, safe_message)

    # ---- unidade mais próxima (geolocalização autorizada; cálculo determinístico, nunca pelo Gemini) --------------------
    def _municipio_in_message(self, message: str) -> str | None:
        kb = self._knowledge
        if kb is None:
            return None
        stop = frozenset(kb.aliases.get("stopwords", []))
        tokens = tokenize(message, stop, use_stem=False)
        for geo_unit in kb.geo_units:
            city_tokens = tokenize(geo_unit.municipio, frozenset(), use_stem=False)
            if city_tokens and contains_sequence(tokens, city_tokens):
                return geo_unit.municipio
        return None

    def _nearest_hint(self, message: str, lat: float | None, lon: float | None) -> str:
        """Frase com a unidade mais próxima (pela localização autorizada ou pela cidade citada); sem nenhuma das duas, pede a cidade."""
        kb = self._knowledge
        ask = "Se me disser sua cidade ou autorizar a localização, eu indico a unidade mais próxima."
        if kb is None:
            return ask
        if lat is not None and lon is not None:
            ranked = kb.nearest_units(lat, lon, limit=1)
            if ranked:
                unit, distance = ranked[0]
                return (f"A unidade mais próxima da sua localização é {kb.unit_name(unit.unit) or unit.unit}, em {unit.municipio}, "
                        f"a cerca de {distance:.1f} km em linha reta.")
            return ask
        municipio = self._municipio_in_message(message)
        geo_unit = kb.geo_unit_for_municipio(municipio) if municipio else None
        if geo_unit is not None:
            return f"Em {geo_unit.municipio} a unidade do Senac que tenho confirmada é {kb.unit_name(geo_unit.unit) or geo_unit.unit}."
        return ask

    def _nearest_unit_reply(self, message: str, lat: float | None, lon: float | None) -> ChatReply | None:
        kb = self._knowledge
        if kb is None or not _NEAREST_UNIT.search(normalize(message)):
            return None
        if lat is not None and lon is not None:
            ranked = kb.nearest_units(lat, lon, limit=3)
            if not ranked:
                return ChatReply(
                    "Ainda não tenho coordenadas confirmadas das unidades para calcular a distância. "
                    "Pode me dizer sua cidade ou bairro?",
                    "knowledge", "no_geo_data", "info",
                )
            parts = [
                f"{kb.unit_name(unit.unit) or unit.unit}, em {unit.municipio}, a cerca de {distance:.1f} km em linha reta"
                for unit, distance in ranked
            ]
            text = f"A unidade mais próxima da sua localização é {parts[0]}."
            if len(parts) > 1:
                text += " Também não ficam longe: " + "; ".join(parts[1:]) + "."
            text += " Essa distância é em linha reta, não é a distância real do trajeto; confirme o caminho no mapa."
            source = kb.sources.get("pb-unidades")
            links = (Link(source.name, source.url),) if source is not None else ()
            return ChatReply(text, "knowledge", None, "info", tuple(unit.unit for unit, _ in ranked), links)
        municipio = self._municipio_in_message(message)
        if municipio is not None:
            geo_unit = kb.geo_unit_for_municipio(municipio)
            if geo_unit is not None:
                name = kb.unit_name(geo_unit.unit) or geo_unit.unit
                text = f"Em {geo_unit.municipio} a unidade do Senac que tenho confirmada é {name}. {geo_unit.note}".strip()
                source = kb.sources.get(geo_unit.source_id) or kb.sources.get("pb-unidades")
                links = (Link(source.name, source.url),) if source is not None else ()
                return ChatReply(text, "knowledge", None, "info", (geo_unit.unit,), links)
            return ChatReply(
                f"Não tenho uma unidade do Senac com localização confirmada em {municipio}. "
                "Posso listar as unidades que já tenho confirmadas, se quiser.",
                "knowledge", "no_geo_data", "info",
            )
        return ChatReply(
            "Posso verificar isso, mas preciso da sua localização ou de sua cidade. Pode me dizer sua cidade ou bairro?",
            "knowledge", "needs_location", "info",
        )

    # ---- portal oficial de matrículas (cache da extração; nunca consulta a rede durante a conversa) ------------------
    def _portal_reply(self, message: str, result) -> ChatReply | None:
        """Pergunta sobre cursos técnicos que a base local não responde com segurança: usa a última extração do portal oficial.

        Não exige a palavra "curso"/"turma" na frase ("Vocês têm Illustrator?" também deve funcionar): quem decide
        se a pergunta tem a ver com cursos é o próprio PortalLookup.answer(), a partir do vocabulário real das
        turmas (unidade, cidade ou palavra que aparece em algum curso); senão ele mesmo devolve None, sem custo.
        """
        if self._portal is None:
            return None
        top = result.hits[0].entry if result.hits else None
        # Pergunta sobre os cursos de uma unidade: a programação real (portal) vale mais que o texto curado.
        top_unconfirmed = bool(top and top.category == "courses" and (top.unit or self._knowledge.effective(top) == "pending"))
        if result.hits and result.confident and not top_unconfirmed:
            return None  # a base já responde com segurança
        return self._portal_text_reply(message)

    def _portal_text_reply(self, message: str) -> ChatReply | None:
        """Consulta direta ao cache do portal oficial (sem checar a base institucional antes)."""
        if self._portal is None:
            return None
        answer = self._portal.answer(message)
        if answer is None:
            return None
        source = self._knowledge.sources.get("pb-programacao-cursos") if self._knowledge is not None else None
        links = (Link(source.name, source.url),) if source is not None else ()
        return ChatReply(answer.text, "portal", None, "info", tuple(f"turma-{i}" for i in answer.offering_ids), links)

    def _cep_jp_priority_reply(self, message: str, guided) -> ChatReply | None:
        """Regra nº 1 da orientação (CEP-JP sempre primeiro): se a Guidance recomendou uma oferta de outra
        unidade ou da EAD, mas o portal tem uma turma real confirmada no CEP-JP para o mesmo assunto, o
        CEP-JP vale mais que o catálogo curado (knowledge/offers.json), que não cobre todas as turmas reais.
        """
        if self._portal is None or self._knowledge is None or not guided.offer_ids:
            return None
        offer = self._knowledge.catalog.get(guided.offer_ids[0])
        if offer is None or offer.tier == 1:
            return None  # já é CEP-JP (ou a oferta não existe mais): nada a sobrepor
        answer = self._portal.answer(f"{message} CEP-JP")
        if answer is None or not answer.offering_ids:
            return None  # o CEP-JP também não tem confirmado: a recomendação da orientação continua valendo
        source = self._knowledge.sources.get("pb-programacao-cursos")
        links = (Link(source.name, source.url),) if source is not None else ()
        return ChatReply(answer.text, "portal", None, "info", tuple(f"turma-{i}" for i in answer.offering_ids), links)

    # ---- camada 2: conhecimento do evento ativo -----------------------------------------------------------------
    def _event_block(self) -> str | None:
        active = self._events.active() if self._events is not None else None
        return event_prompt_block(active.event) if active is not None else None

    def _answer_event(self, session_id, message: str, safe_message: str, active) -> ChatReply | None:
        mentions = active.mentions_event(message)
        if _WANTS_COURSES.search(normalize(message)) and not mentions:
            return None  # interesse em cursos: a orientação do Senac vem primeiro
        result = active.search(message)
        if not (result.hits and result.confident):
            return None
        if self._knowledge is not None and not mentions:
            institutional = self._knowledge.search(message)
            if institutional.hits and institutional.confident and institutional.hits[0].score > result.hits[0].score:
                return None  # a pergunta é mais claramente sobre o Senac do que sobre o evento
        ids = tuple(result.ids)
        extractive = active.answer_for(result)
        if self._usable():
            return ChatReply(extractive, "event", self._usable(), "info", ids)
        context = active.context_for(result)
        try:
            text = self._provider.generate(self._contexts.get(session_id), safe_message, context=context, event=event_prompt_block(active.event))
        except AIError as error:
            self._record_error(error)
            return ChatReply(extractive, "event", error.kind, "info", ids)
        except Exception:  # noqa: BLE001
            logger.exception("Falha inesperada no provedor de IA; respondendo direto com o conhecimento do evento.")
            self._status = "unavailable"
            return ChatReply(extractive, "event", "unavailable", "info", ids)
        self._status = "available"
        invented = ungrounded_numbers(text, context, message)
        if invented:
            logger.warning("Resposta do Gemini descartada: números fora dos dados do evento (%s).", ", ".join(invented))
            return ChatReply(extractive, "event", "ungrounded", "info", ids)
        return ChatReply(text, "event", None, "info", ids)

    def _event_without_data(self, message: str, safe_message: str, active) -> ChatReply:
        """Pergunta sobre o evento que as camadas 1 e 2 não respondem: pesquisa externa validada ou "não tenho confirmação"."""
        external = self._external(safe_message, active)
        if external is not None:
            return external
        website = active.event.website
        links = (Link("Site oficial do evento", website),) if website.startswith("https://") else ()
        text = f"Não tenho essa informação do {active.event.name} confirmada. Para saber com segurança, consulte o site oficial do evento ou a organização."
        return ChatReply(text, "event", "no_match", "info", links=links)

    # ---- camada 3: pesquisa externa (dado não confiável) ------------------------------------------------------------
    def _external(self, safe_message: str, active) -> ChatReply | None:
        if not self._external_enabled or self._usable():
            return None
        key = normalize(safe_message)
        now = time.monotonic()
        cached = self._external_cache.get(key)
        if cached and now - cached[0] < EXTERNAL_CACHE_SECONDS:
            return cached[1]
        if now - self._external_last < EXTERNAL_MIN_GAP_SECONDS:
            return None
        self._external_last = now
        reply = self._search_reply(safe_message, active)
        self._external_cache[key] = (now, reply)
        while len(self._external_cache) > 50:
            self._external_cache.popitem(last=False)
        return reply

    def _search_reply(self, safe_message: str, active) -> ChatReply | None:
        try:
            answer: SearchAnswer = self._provider.search(safe_message, event_prompt_block(active.event))
        except AIError as error:
            self._record_error(error)
            return None
        except Exception:  # noqa: BLE001 - a pesquisa é opcional
            logger.exception("Falha inesperada na pesquisa externa.")
            return None
        sources = [(title, url) for title, url in answer.sources if url.startswith("https://")][:2]
        text = self._policy.speakable(answer.text, EXTERNAL_MAX_WORDS)
        if not sources or not text or check_message(text) is not None:
            return None  # sem fonte pública verificável, ou conteúdo com cara de instrução: descartado
        if not re.search(r"não encontr|nao encontr", text, re.IGNORECASE):
            text = f"{text} {EXTERNAL_HEDGE}"
        try:
            self._events.store.add_history(active.event.id, "pesquisa_externa", f"Consulta externa respondida com {len(sources)} fonte(s).",
                                           {"dominios": sorted({url.split('/')[2] for _, url in sources})})
        except Exception:  # noqa: BLE001 - o histórico nunca impede a resposta
            logger.warning("Não foi possível registrar a pesquisa externa no histórico do evento.")
        links = tuple(Link(title or url.split("/")[2], url) for title, url in sources)
        return ChatReply(text, "external", None, "info", links=links)

    # ---- contexto da conversa atual -------------------------------------------------------------------------------
    def _turn(self, session_id: str | None, kind: str) -> int:
        key = f"{session_id}:{kind}"
        count = self._variants.get(key, 0)
        self._variants[key] = count + 1
        return count

    def _vary(self, session_id: str | None, reply: ChatReply) -> ChatReply:
        """A resposta padrão de "não sei" alterna entre variações para não soar repetida."""
        if reply.text == FALLBACK_GENERIC:
            text = FALLBACK_VARIANTS[self._turn(session_id, "fallback") % len(FALLBACK_VARIANTS)]
            return replace(reply, text=text)
        return reply

    def _remember(self, session_id: str | None, unit_alias: str | None = None, hint: str | None = None) -> None:
        if not session_id:
            return
        subject = self._subjects.pop(session_id, _Subject())
        subject.unit_alias = unit_alias or subject.unit_alias
        subject.hint = hint or subject.hint
        self._subjects[session_id] = subject
        while len(self._subjects) > MAX_SUBJECT_SESSIONS:
            self._subjects.popitem(last=False)

    def _remember_result(self, session_id: str | None, result) -> None:
        kb = self._knowledge
        alias = None
        if result.unit and kb is not None:
            aliases = kb.aliases.get("units", {}).get(result.unit, {}).get("aliases", [])
            alias = aliases[0] if aliases else None
        top = result.hits[0].entry
        self._remember(session_id, alias, top.title if top.category in SUBJECT_CATEGORIES else None)

    def _with_unit(self, session_id: str | None, message: str) -> str:
        """"Tem curso de gastronomia lá?": o "lá" é a unidade de que se falava na conversa atual."""
        subject = self._subjects.get(session_id) if session_id else None
        if subject is None or not subject.unit_alias or self._knowledge is None:
            return message
        if not _DEICTIC.search(normalize(message)) or self._knowledge.detect_units(message):
            return message
        return f"{message} {subject.unit_alias}"

    def _contextual_query(self, session_id: str | None, message: str) -> str:
        """Pergunta curta e sem assunto próprio ("E o telefone?") herda a unidade/assunto da conversa atual."""
        subject = self._subjects.get(session_id) if session_id else None
        if subject is None or self._knowledge is None:
            return message
        norm = normalize(message)
        if len(norm.split()) > MAX_FOLLOW_UP_WORDS or not _FOLLOW_UP.search(norm) or "senac" in norm:
            return message
        if len(tokenize(message, frozenset(self._knowledge.aliases.get("stopwords", [])))) > 2 or self._knowledge.detect_units(message):
            return message
        extra = " ".join(x for x in (subject.unit_alias, subject.hint) if x)
        return f"{message} {extra}".strip()

    def _finish(self, session_id: str | None, message: str, routed: ChatReply) -> ChatReply:
        generated = routed.source in ("gemini", "fallback", "external")
        outcome = self._policy.enforce(routed.text, generated=generated, free_context=bool(_FREE_TOPIC.search(normalize(message))))
        reply = replace(routed, text=outcome.text)
        if outcome.changed:
            blocked = {"vazamento_de_instrucoes", "credencial", "dado_pessoal", "identidade_humana"} & set(outcome.issues)
            if blocked:
                # Resposta substituída por texto fixo da política: nada mais é acrescentado.
                return replace(reply, source="policy", reason=",".join(outcome.issues), knowledge=(), links=(), follow_up=None)
            reply = replace(reply, reason=reply.reason or ",".join(outcome.issues))

        text = reply.text
        words = len(text.split())
        if reply.follow_up and "?" not in text[-80:] and words + len(reply.follow_up.split()) <= MAX_WORDS_WITH_FOLLOW_UP:
            text = f"{text} {reply.follow_up}"
        elif (
            self._guidance is not None
            and reply.source in ("knowledge", "gemini", "fallback", "local", "event", "external")
            and reply.intent in (None, "info")
            and reply.reason != "no_match"
            and "?" not in text[-80:]
        ):
            # Pergunta sem relação direta com formação: responde primeiro e conclui com sugestão pertinente, sem insistir.
            active = self._events.active() if self._events is not None else None
            hint = " ".join([active.event.area] + list(active.event.keywords)) if active is not None else ""
            suggestion = self._guidance.suggestion(session_id, message, text, hint, hint_first=reply.source in ("event", "external"))
            if suggestion is not None:
                text = f"{text} {suggestion.text}"
                reply = replace(reply, links=reply.links + suggestion.links, knowledge=reply.knowledge + suggestion.offer_ids)
        return replace(reply, text=text, follow_up=None)

    def _usable(self) -> str | None:
        """Motivo pelo qual o Gemini não pode ser usado agora, ou None se pode."""
        if not self._provider.is_configured():
            return "not_configured"
        if self._status == "invalid_key":
            return "invalid_key"
        return None

    @staticmethod
    def _follow_up_for(result) -> str | None:
        if result.corporate:
            return CORPORATE_ASK
        if any(hit.entry.category == "social" for hit in result.hits[:2]):
            return SOCIAL_ASK
        return None

    def _answer_with_knowledge(self, session_id, message: str, safe_message: str, result) -> ChatReply:
        kb = self._knowledge
        ids = tuple(result.ids)
        follow_up = self._follow_up_for(result)
        extractive = kb.answer_for(result)
        blocked = self._usable()
        if blocked:
            return ChatReply(extractive, "knowledge", blocked, "info", ids, follow_up=follow_up)

        context = kb.context_for(result)
        try:
            text = self._provider.generate(
                self._contexts.get(session_id), safe_message, context=context, corporate=result.corporate, event=self._event_block()
            )
        except AIError as error:
            self._record_error(error)
            logger.warning("Gemini indisponível (%s); respondendo direto com a base de conhecimento.", error.kind)
            return ChatReply(extractive, "knowledge", error.kind, "info", ids, follow_up=follow_up)
        except Exception:  # noqa: BLE001
            logger.exception("Falha inesperada no provedor de IA; respondendo direto com a base de conhecimento.")
            self._status = "unavailable"
            return ChatReply(extractive, "knowledge", "unavailable", "info", ids, follow_up=follow_up)

        self._status = "available"
        invented = ungrounded_numbers(text, context, message)
        if invented:
            # O Gemini trouxe números que não estão nos dados oficiais: vale o texto da base.
            logger.warning("Resposta do Gemini descartada: números fora da base (%s).", ", ".join(invented))
            return ChatReply(extractive, "knowledge", "ungrounded", "info", ids, follow_up=follow_up)
        return ChatReply(text, "gemini", None, "info", ids, follow_up=follow_up)

    def _answer_general(self, session_id, message: str, safe_message: str) -> ChatReply:
        """Perguntas gerais (fora da base): Gemini sem contexto institucional ou contingência local."""
        blocked = self._usable()
        if blocked:
            return ChatReply(contingency_answer(message, self._knowledge), "fallback", blocked)
        try:
            text = self._provider.generate(self._contexts.get(session_id), safe_message, event=self._event_block())
        except AIError as error:
            self._record_error(error)
            logger.warning("Usando contingência local (motivo: %s).", error.kind)
            return ChatReply(contingency_answer(message, self._knowledge), "fallback", error.kind)
        except Exception:  # noqa: BLE001 - nenhuma falha do provedor pode derrubar o chat
            logger.exception("Falha inesperada no provedor de IA; usando contingência local.")
            self._status = "unavailable"
            return ChatReply(contingency_answer(message, self._knowledge), "fallback", "unavailable")

        self._status = "available"
        return ChatReply(text, "gemini")
