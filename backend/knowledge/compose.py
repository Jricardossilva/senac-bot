"""Composição de respostas a partir da base: contexto para o Gemini, resposta extrativa e verificação de números."""
import re
from datetime import date

from backend.knowledge.models import LEVEL_LABELS
from backend.knowledge.search import SearchResult

SCOPE_GENERAL = "Senac Paraíba (informação geral, não específica de unidade)"
STATUS_LABELS = {
    "verified": "verificada em fonte oficial",
    "review": "A CONFIRMAR (revisão pendente)",
    "stale": "POSSIVELMENTE DESATUALIZADA",
    "pending": "SEM CONFIRMAÇÃO",
}


NATURE_LABELS = {
    "permanent": "AÇÃO/PROGRAMA PERMANENTE (descrição institucional; sem edição ou data confirmada)",
    "historical": "FATO HISTÓRICO (já ocorreu; não dizer que está acontecendo)",
    "open": "VIGENTE (ocorrência ou inscrições confirmadas na fonte)",
    "unconfirmed": "SEM CONFIRMAÇÃO DE ESTAR ACONTECENDO",
}


def format_date(value: date) -> str:
    return value.strftime("%d/%m/%Y")


def _scope(entry, unit_names: dict[str, str]) -> str:
    if entry.unit:
        return f"Unidade: {unit_names.get(entry.unit, entry.unit)}"
    if entry.level == "brasil":
        return LEVEL_LABELS["brasil"]
    return SCOPE_GENERAL


def format_context(result: SearchResult, effective, unit_names: dict[str, str], sources_of) -> str:
    """Texto entregue ao Gemini: somente estes dados podem sustentar fatos institucionais."""
    lines: list[str] = []
    for hit in result.hits:
        entry = hit.entry
        status = effective(entry)
        names = "; ".join(s.name for s in sources_of(entry)) or entry.source_note or "conteúdo do projeto"
        lines.append(
            f"[{entry.id}] {entry.title}\n"
            f"Âmbito: {_scope(entry, unit_names)} | Consultado em {format_date(entry.consulted_at)} | "
            f"Situação: {STATUS_LABELS[status]}"
            + (f" | Natureza: {NATURE_LABELS[entry.nature]}" if entry.nature else "")
            + f" | Fonte: {names}\n"
            f"{entry.content}"
        )
        if entry.unit_note:
            lines.append(f"Atenção: {entry.unit_note}")
    return "\n\n".join(lines)


def first_sentence(text: str) -> str:
    match = re.match(r"(.+?[.!?])(\s|$)", text.strip())
    return match.group(1) if match else text.strip()


_CAUTION_MARKERS = ("confirm", "procure", "consulte", "canais oficiais", "atendimento oficial", "3208-3100", "pode ter mudado")


def _already_cautious(content: str) -> bool:
    """A própria entrada já manda confirmar nos canais oficiais? Evita repetir a mesma orientação."""
    lowered = content.lower()
    return any(marker in lowered for marker in _CAUTION_MARKERS)


def extractive_answer(result: SearchResult, effective, channels: str, empresas_intro: str | None) -> str:
    """Resposta direta da base (sem IA): conteúdo da melhor entrada + avisos de atualidade e de escopo."""
    top = result.hits[0].entry
    parts = [top.content]
    status = effective(top)
    if status in ("review", "pending") and _already_cautious(top.content):
        status = "verified"  # a orientação já está no texto da entrada
    if status == "stale":
        parts.append(f"Essa informação foi consultada em {format_date(top.consulted_at)} e pode ter mudado; confirme em {channels}.")
    elif status == "review":
        parts.append(f"Essa informação precisa de confirmação; confirme em {channels}.")
    elif status == "pending":
        parts.append(f"Para saber com segurança, procure {channels}.")
    if result.unit and top.unit is None and top.category in ("courses", "news_events", "programs"):
        parts.append(
            f"Atenção: isso vale para o Senac Paraíba em geral e não confirma que seja da unidade {result.unit_name}."
        )
    if result.corporate and top.category != "empresas" and empresas_intro:
        parts.append(f"Para empresas: {empresas_intro}")
    return " ".join(parts)


def comparison_answer(result: SearchResult, unit_names: dict[str, str]) -> str:
    """Pergunta que cita duas ou mais unidades: uma frase de cada, sempre rotulada pela unidade."""
    parts = []
    for unit in result.units:
        entry = next((h.entry for h in result.hits if h.entry.unit == unit), None)
        if entry is not None:
            parts.append(f"{unit_names.get(unit, unit)}: {first_sentence(entry.content)}")
    return " ".join(parts)


def no_confirmation_text(channels: str) -> str:
    return f"Não tenho essa informação confirmada. Para saber com segurança, procure {channels}."


_NUMBER = re.compile(r"\d[\d.,]*")


def _numbers(text: str) -> set[str]:
    return {re.sub(r"\D", "", n) for n in _NUMBER.findall(text) if len(re.sub(r"\D", "", n)) >= 2}


def ungrounded_numbers(reply: str, context: str, user_message: str) -> list[str]:
    """Números (telefones, anos, valores) da resposta que não existem no contexto nem na pergunta."""
    allowed = _numbers(context) | _numbers(user_message)
    found = sorted(_numbers(reply) - allowed)
    if re.search(r"R\$\s*\d", reply) and not re.search(r"R\$\s*\d", context):
        found.append("R$")
    return found
