"""Verificação de prontidão para o evento: internet, Gemini, hardware e emergência.

O áudio (microfone, reconhecimento e voz) só pode ser verificado no navegador e é complementado pela interface.
Status: ok | warning (funciona em contingência) | error (impede a demonstração).
"""
import logging
import socket

logger = logging.getLogger("senac_bot.preflight")

INTERNET_HOST = "generativelanguage.googleapis.com"

_GEMINI = {
    "not_configured": (
        "warning",
        "Gemini não configurado: o robô usa somente respostas locais.",
        "Coloque a chave em GEMINI_API_KEY no arquivo .env (https://aistudio.google.com/apikey) e reinicie.",
    ),
    "invalid_key": (
        "warning",
        "O Gemini recusou a chave de API.",
        "Gere uma nova chave em https://aistudio.google.com/apikey, atualize o .env e reinicie.",
    ),
    "rate_limited": (
        "warning",
        "A cota do Gemini acabou: o robô usa respostas locais por enquanto.",
        "Aguarde a renovação da cota ou escolha outro modelo em GEMINI_MODEL.",
    ),
    "model_unavailable": (
        "warning",
        "O modelo configurado em GEMINI_MODEL não está disponível.",
        "Escolha um modelo da lista oficial (ai.google.dev/gemini-api/docs/models) e reinicie.",
    ),
    "unavailable": (
        "warning",
        "Não foi possível falar com o Gemini agora; o robô usa respostas locais.",
        "Verifique a internet e clique em Verificar sistema novamente.",
    ),
    "configured": (
        "warning",
        "Gemini configurado, mas ainda não confirmado.",
        "Clique em Verificar sistema novamente.",
    ),
}


def check_internet(host: str = INTERNET_HOST, port: int = 443, timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError as error:
        logger.info("Sem acesso à internet (%s).", type(error).__name__)
        return False


def _item(id_: str, label: str, status: str, message: str, action: str = "") -> dict[str, str]:
    return {"id": id_, "label": label, "status": status, "message": message, "action": action}


def build_preflight(internet_ok: bool, ai_status: str, snapshot: dict[str, object]) -> dict[str, object]:
    checks: list[dict[str, str]] = []

    if internet_ok:
        checks.append(_item("internet", "Internet", "ok", "Conectada."))
    else:
        checks.append(
            _item(
                "internet",
                "Internet",
                "warning",
                "Sem internet: o robô usa respostas locais, e o reconhecimento de voz do navegador também não funciona.",
                "Verifique o Wi-Fi ou a rede do evento. Digitar mensagens e a demonstração continuam funcionando.",
            )
        )

    if ai_status == "available":
        checks.append(_item("gemini", "Gemini (IA)", "ok", "Disponível e respondendo."))
    else:
        status, message, action = _GEMINI.get(ai_status, _GEMINI["unavailable"])
        if not internet_ok and ai_status != "not_configured":
            message = "Gemini inacessível porque não há internet; o robô usa respostas locais."
            action = "Restabeleça a internet e clique em Verificar sistema."
        checks.append(_item("gemini", "Gemini (IA)", status, message, action))

    error = snapshot.get("hardware_error")
    if error:
        checks.append(
            _item("hardware", "Hardware", "warning", f"Hardware físico indisponível; simulador ativo. {error}",
                  "Continue com o simulador ou revise a conexão do Hub.")
        )
    elif snapshot.get("hardware_mode") == "simulation":
        checks.append(_item("hardware", "Hardware", "ok", "Modo simulado ativo (avatar na tela, sem hardware físico)."))
    else:
        checks.append(_item("hardware", "Hardware", "ok", "Modo físico ativo."))

    knowledge = snapshot.get("knowledge")
    if isinstance(knowledge, dict):
        if not knowledge.get("loaded"):
            checks.append(
                _item("knowledge", "Base de conhecimento", "warning",
                      "A base de conhecimento institucional não foi carregada: o robô responde só com o conteúdo geral.",
                      "Verifique a pasta knowledge/ e os logs (python -m backend.knowledge.update --report).")
            )
        elif knowledge.get("stale_core") or knowledge.get("sources_review") or knowledge.get("sources_failing"):
            checks.append(
                _item("knowledge", "Base de conhecimento", "warning",
                      f"{knowledge['entries']} entradas; {knowledge.get('stale_core', 0)} informações centrais possivelmente "
                      f"desatualizadas e {knowledge.get('sources_review', 0)} fontes oficiais alteradas sem revisão: "
                      "o robô avisa quando a informação pode ter mudado.",
                      "Atualize as fontes (scripts\\atualizar-conhecimento.ps1) e revise os itens indicados.")
            )
        else:
            checks.append(_item("knowledge", "Base de conhecimento", "ok", f"{knowledge['entries']} entradas carregadas; "
                                f"{knowledge.get('pending', 0)} lacunas conhecidas registradas como pendência "
                                f"e {knowledge.get('stale', 0)} notícias/eventos datados (o robô avisa que podem ter mudado)."))

    if snapshot.get("emergency_stop"):
        checks.append(
            _item("emergency", "Parada de emergência", "error", "A parada de emergência está acionada.",
                  "Libere a parada no painel do operador antes de iniciar a demonstração.")
        )
    else:
        checks.append(_item("emergency", "Parada de emergência", "ok", "Liberada."))

    return {"checks": checks, "ready": all(c["status"] != "error" for c in checks)}
