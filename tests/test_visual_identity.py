"""Identidade visual Senac Paraíba: regras que a interface do visitante e o avatar precisam cumprir."""
import re
from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)
HTML = Path("frontend/index.html").read_text(encoding="utf-8")
CSS = Path("frontend/app.css").read_text(encoding="utf-8")
JS = Path("frontend/app.js").read_text(encoding="utf-8")


def visitor_section() -> str:
    start = HTML.index('<section id="visitor"')
    end = HTML.index('<section id="operator"')
    return HTML[start:end]


def test_visitor_ui_shows_no_technical_ai_information() -> None:
    text = visitor_section().lower()
    for forbidden in ("gemini", "modo híbrido", "contingência", "resposta local", "fastapi", "api "):
        assert forbidden not in text, forbidden
    assert "visitor-ai-status" not in HTML
    assert "visitor-ai-status" not in JS


def test_response_origin_is_hidden_unless_operator_enables_it() -> None:
    assert re.search(r"\.message-source\s*\{[^}]*display:\s*none", CSS)
    assert "body.show-source .message-source" in CSS
    assert 'id="toggle-source"' in HTML and "show-source" in JS


def test_avatar_is_a_single_interactive_svg_template() -> None:
    template = HTML[HTML.index('<template id="avatar-template">'):HTML.index("</template>")]
    for part in ("head", "eyes", "mouth", "arm-left", "arm-right", "torso", "wheel", "sensor", "ears", "chest-label"):
        assert f'class="{part}' in template or f" {part}" in template, part
    assert "SENAC BOT" in template
    assert "<image" not in template and "<img" not in template  # nada de imagem estática no avatar
    assert HTML.count('data-avatar="') == 2  # visitante e simulador usam o mesmo modelo
    assert "mountAvatars" in JS


def test_senac_palette_and_identity_present() -> None:
    for token in ("--blue-700", "--orange", "--white"):
        assert token in CSS
    page = client.get("/").text
    assert "Senac Paraíba" in page and "CEP João Pessoa" in page
    assert "Tecnologia que conversa com você" in page


def png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def test_official_logos_are_present_and_unaltered() -> None:
    """Arquivos fornecidos pelo Senac, com as dimensões originais (sem recorte nem redimensionamento)."""
    brand = Path("frontend/brand")
    assert png_size(brand / "senac-logo.png") == (2000, 1182)
    assert png_size(brand / "senac-fecomercio-sesc-horizontal.png") == (468, 151)
    assert png_size(brand / "senac-fecomercio-sesc-vertical.png") == (1404, 1482)
    for name in ("senac-logo.png", "senac-fecomercio-sesc-horizontal.png"):
        assert f"/assets/brand/{name}" in HTML


def test_logos_keep_proportions_and_white_version_is_css_only() -> None:
    """Altura fixa com largura automática (sem distorcer); branco só por filtro CSS, sem novo arquivo de marca."""
    for selector in (".brand-logo", ".stage-logo", ".footer-logo"):
        rule = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", CSS).group(1)
        assert "height:" in rule and "width: auto" in rule, selector
    assert "brightness(0) invert(1)" in CSS
    logo_pngs = {p.name for p in Path("frontend/brand").glob("*.png")} - {p.name for p in Path("frontend/brand").glob("favicon*.png")}
    assert logo_pngs == {"senac-fecomercio-sesc-horizontal.png", "senac-fecomercio-sesc-vertical.png", "senac-logo.png"}


def test_header_logo_served_as_image() -> None:
    resp = client.get("/assets/brand/senac-logo.png")
    assert resp.status_code == 200 and resp.headers["content-type"] == "image/png"


def test_voice_states_drive_avatar_animation() -> None:
    assert 'data-voice="listening"' in CSS and 'data-voice="speaking"' in CSS
    assert "dataset.voice" in JS


def test_all_expressions_have_visual_rules() -> None:
    for expression in ("happy", "curious", "thinking", "speaking", "surprised", "sad", "disconnected"):
        assert f'data-expression="{expression}"' in CSS, expression


def test_responsive_breakpoints_exist() -> None:
    for query in ("max-width: 1100px", "max-width: 900px", "max-width: 680px", "prefers-reduced-motion"):
        assert query in CSS


def test_new_assets_are_served() -> None:
    assert client.get("/assets/brand/senac-fecomercio-sesc-horizontal.png").status_code == 200
    assert client.get("/assets/app.css").status_code == 200


# ---------------- Conversa por voz como interação principal ----------------

CONVERSATION_JS = Path("frontend/conversation.js").read_text(encoding="utf-8")
SPEECH_JS = Path("frontend/speech.js").read_text(encoding="utf-8")


def test_visitor_screen_is_voice_first() -> None:
    """Sem campo de texto, formulário, botão enviar nem atalhos que sugiram digitar."""
    section = visitor_section()
    for forbidden in ("<input", "<textarea", "<form", "send-button", "chat-form", "data-prompt", "suggestion"):
        assert forbidden not in section, forbidden
    assert 'id="conversation-button"' in section and "INICIAR CONVERSA" in section
    for needed in ('id="messages"', 'id="visitor-state"', 'id="stop-speech"', "SENAC BOT"):
        assert needed in section, needed


def test_operator_keeps_a_text_test_outside_the_visitor_screen() -> None:
    operator = HTML[HTML.index('<section id="operator"'):HTML.index('<section id="simulator"')]
    assert 'id="op-test-form"' in operator and 'id="op-test-message"' in operator
    assert 'id="op-test-form"' not in visitor_section()


def test_conversation_state_machine_defines_all_states() -> None:
    for state in ("idle", "requesting", "listening", "processing", "speaking", "error", "unavailable", "ended"):
        assert f'"{state}"' in CONVERSATION_JS, state
    for rule in ("isEcho", "duplicateWindowMs", "maxNetworkFailures", "idleTimeoutMs", "interrupt()", "speech.speaking"):
        assert rule in CONVERSATION_JS, rule


def test_recognition_uses_pt_br_and_microphone_is_released() -> None:
    assert 'lang = "pt-BR"' in SPEECH_JS or 'lang: "pt-BR"' in JS
    # a permissão abre o microfone só para acioná-la e fecha o fluxo na hora
    assert "getUserMedia" in SPEECH_JS and "getTracks().forEach((track) => track.stop())" in SPEECH_JS
    assert "recognizer.abort()" in CONVERSATION_JS or "this.#recognizer.abort()" in CONVERSATION_JS
    assert "conversation.stop(" in JS and 'addEventListener("pagehide"' in JS


def test_only_recognized_text_reaches_the_backend() -> None:
    """O navegador só envia texto (e, se autorizada, lat/lon) ao /chat; nenhum áudio, blob ou FormData sai da página."""
    assert 'const body = { message, session_id: sessionId };' in JS
    assert "postJson(\"/chat\", body)" in JS
    for forbidden in ("FormData", "Blob(", "MediaRecorder", "audio/"):
        assert forbidden not in JS + CONVERSATION_JS + SPEECH_JS, forbidden
