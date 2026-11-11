"""Política de saída: toda resposta (local, da base, do Gemini ou de contingência) passa por aqui antes de sair.

Garante, no backend e sem depender do prompt, que a resposta não vaza instruções internas, credenciais ou dados
pessoais, não se diz humana, não promete vagas/inscrições sem confirmação, não generaliza gratuidade e é falável
(sem endereços de internet nem formatação).
"""
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from backend.knowledge.base import EMAIL_RE, PHONE_RE, digits_of
from backend.knowledge.text import normalize
from backend.policy.messages import (
    CONFIDENTIAL,
    FREE_CAVEAT,
    IDENTITY,
    MANIPULATION,
    NO_EVALUATION,
    UNCONFIRMED_AVAILABILITY,
)
from backend.policy.reputation import output_issue

logger = logging.getLogger("senac_bot.policy")

MAX_WORDS_GENERATED = 100  # limite duro para texto gerado pela IA (a meta é ~70 palavras)
SHINGLE_WORDS = 8

_SECRET_PATTERNS = (
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"(?i)\b(api[_ ]?key|senha|password|token|secret)\s*[:=]\s*\S{4,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{12,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bGEMINI_API_KEY\b"),
    re.compile(r"\b[A-Za-z0-9+/_\-]{40,}={0,2}\b"),
)
_CPF = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b|\b\d{11}\b")
_HUMAN = re.compile(r"(?<!nao )(?<!nem )\b(sou|eu sou|somos) (um |uma )?(humano|humana|ser humano|pessoa|funcionario|funcionaria|atendente|colaborador|colaboradora|atendente humano)\b")
_URL = re.compile(r"(?i)\b(?:https?://|www\.)\S+")
_AVAILABILITY = re.compile(
    r"\b(inscricoes? (estao |esta )?(abertas?|disponiveis)|vagas? (estao |esta )?(abertas?|disponiveis|garantidas?)|"
    r"(ha|tem|temos|existem?|restam) vagas?|turmas? (abertas?|disponiveis)|(esta|estao) acontecendo (agora|hoje|neste momento)|"
    r"acontecendo agora|acontece hoje|matriculas? (abertas?|disponiveis)|ainda da tempo de se inscrever)\b"
)
_NEGATION = re.compile(r"\b(nao|sem|nenhum|nenhuma|nem|ainda nao|se houver|caso haja|quando houver|confirm\w+|verifi\w+|consult\w+)\b")
_ALL_FREE = re.compile(r"(?<!nem )\b(todos|todas)\b[^.?!]{0,30}\b(cursos?|vagas?|formacoes)\b[^.?!]{0,30}\bgratuit\w*|\btudo (e )?gratuito\b|\bsempre gratuit\w*")
_FREE_WORD = re.compile(r"\bgratuit\w*|\bde graca\b|\bsem custo\b")
_FREE_CAUTION = re.compile(r"\b(depende|nem todos|nem todas|criterio|criterios|condicoes|condicao|programacao)\b")
_MARKDOWN = re.compile(r"[*_`#>]+|^\s*[-•]\s+", re.MULTILINE)


@dataclass(frozen=True)
class Outcome:
    text: str
    issues: tuple[str, ...] = field(default_factory=tuple)

    @property
    def changed(self) -> bool:
        return bool(self.issues)


def _shingles(texts: tuple[str, ...]) -> frozenset[str]:
    out: set[str] = set()
    for text in texts:
        words = normalize(text).split()
        for i in range(len(words) - SHINGLE_WORDS + 1):
            out.add(" ".join(words[i:i + SHINGLE_WORDS]))
    return frozenset(out)


class OutboundPolicy:
    """Aplicada a TODA resposta. `protected_texts` são os textos internos que nunca podem aparecer (prompts);
    `secrets` são valores sigilosos (chave da API etc.); `emails`/`numbers` são os contatos públicos da base."""

    def __init__(
        self,
        protected_texts: tuple[str, ...] = (),
        secrets: tuple[str, ...] = (),
        emails: frozenset[str] = frozenset(),
        numbers: frozenset[str] = frozenset(),
        contacts: Callable[[], tuple[frozenset[str], frozenset[str]]] | None = None,
    ) -> None:
        self._shingles = _shingles(protected_texts)
        self._secrets = tuple(s for s in secrets if s and len(s) >= 8)
        self._emails = emails
        self._numbers = numbers
        self._contacts = contacts  # contatos publicados em itens CONFIRMADOS do evento ativo (muda com o evento)

    # ---- verificações ----------------------------------------------------------------------------------------------
    def _leaks_prompt(self, norm: str) -> bool:
        if "system prompt" in norm or "prompt de sistema" in norm or "dados oficiais desta pergunta" in norm:
            return True
        words = norm.split()
        return any(" ".join(words[i:i + SHINGLE_WORDS]) in self._shingles for i in range(len(words) - SHINGLE_WORDS + 1))

    def _leaks_secret(self, text: str) -> bool:
        if any(secret in text for secret in self._secrets):
            return True
        return any(p.search(text) for p in _SECRET_PATTERNS)

    def _leaks_personal(self, text: str) -> bool:
        if _CPF.search(text):
            return True
        emails, numbers = self._emails, self._numbers
        if self._contacts is not None:
            extra_emails, extra_numbers = self._contacts()
            emails, numbers = emails | extra_emails, numbers | extra_numbers
        if any(email.lower() not in emails for email in EMAIL_RE.findall(text)):
            return True
        return any(digits_of(m) not in numbers for m in PHONE_RE.findall(text))

    @staticmethod
    def _drop_unconfirmed_availability(text: str) -> str | None:
        """Remove frases que afirmam vaga/inscrição aberta sem ressalva. None = nada a mudar."""
        sentences = re.split(r"(?<=[.!?])\s+", text.strip())
        kept = [s for s in sentences if not (_AVAILABILITY.search(normalize(s)) and not _NEGATION.search(normalize(s)))]
        if len(kept) == len(sentences):
            return None
        return " ".join(kept).strip()

    @staticmethod
    def speakable(text: str, max_words: int | None = None) -> str:
        """Texto para voz: sem endereços de internet nem marcações; limite de palavras opcional (corte em frase)."""
        cleaned = _URL.sub("", text)
        cleaned = _MARKDOWN.sub("", cleaned)
        cleaned = re.sub(r"\s+([,.;:!?])", r"\1", re.sub(r"[ \t]+", " ", cleaned.replace("\n", " "))).strip()
        if max_words and len(cleaned.split()) > max_words:
            kept: list[str] = []
            total = 0
            for sentence in re.split(r"(?<=[.!?])\s+", cleaned):
                words = len(sentence.split())
                if kept and total + words > max_words:
                    break
                kept.append(sentence)
                total += words
            cleaned = " ".join(kept)
        return cleaned

    # ---- aplicação -------------------------------------------------------------------------------------------------
    def enforce(self, text: str, generated: bool = False, free_context: bool = False) -> Outcome:
        """Devolve o texto seguro e a lista de problemas corrigidos. `generated`: texto livre da IA (limite de palavras);
        `free_context`: a conversa trata de gratuidade (a ressalva é exigida mesmo em textos da base)."""
        issues: list[str] = []
        norm = normalize(text)
        if self._leaks_prompt(norm):
            issues.append("vazamento_de_instrucoes")
            return Outcome(MANIPULATION, tuple(issues))
        no_urls = _URL.sub(" ", text)  # endereços longos não são credenciais nem telefones
        if self._leaks_secret(no_urls):
            issues.append("credencial")
            return Outcome(CONFIDENTIAL, tuple(issues))
        if self._leaks_personal(no_urls):
            issues.append("dado_pessoal")
            return Outcome(CONFIDENTIAL, tuple(issues))
        if _HUMAN.search(norm):
            issues.append("identidade_humana")
            return Outcome(IDENTITY, tuple(issues))

        if generated:
            issue = output_issue(text)
            if issue:
                issues.append(issue)
                return Outcome(NO_EVALUATION, tuple(issues))

        result = text
        reduced =self._drop_unconfirmed_availability(result)
        if reduced is not None:
            issues.append("disponibilidade_sem_confirmacao")
            result = reduced if reduced else UNCONFIRMED_AVAILABILITY
            if reduced:
                result = f"{reduced} {UNCONFIRMED_AVAILABILITY}"
        norm_result = normalize(result)
        if _ALL_FREE.search(norm_result):
            issues.append("gratuidade_generalizada")
            sentences = re.split(r"(?<=[.!?])\s+", result.strip())
            kept = [s for s in sentences if not _ALL_FREE.search(normalize(s))]
            result = " ".join(kept + [FREE_CAVEAT]).strip()
        elif (generated or free_context) and _FREE_WORD.search(norm_result) and not _FREE_CAUTION.search(norm_result):
            issues.append("gratuidade_sem_ressalva")
            result = f"{result.rstrip()} {FREE_CAVEAT}"
        spoken = self.speakable(result, MAX_WORDS_GENERATED if generated else None)
        if spoken != result:
            issues.append("formatacao_para_voz")
        if issues:
            logger.info("Política de saída aplicada: %s.", ", ".join(issues))
        return Outcome(spoken, tuple(issues))
