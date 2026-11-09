from pathlib import Path

from fastapi.testclient import TestClient

import backend.main as main
from backend.ai.gemini import GeminiProvider
from backend.ai.service import ChatService

client = TestClient(main.app)
SENTINEL = "AIzaSy-CHAVE-SECRETA-DE-TESTE-0123456789"


def test_api_key_never_reaches_the_browser(monkeypatch) -> None:
    """A chave só existe no provedor do backend: nenhuma rota nem arquivo estático a devolve."""
    provider = GeminiProvider(SENTINEL, "modelo-x", max_retries=0, client=_BrokenClient())
    monkeypatch.setattr(main, "chat_service", ChatService(provider))
    responses = [
        client.get("/"),
        client.get("/health"),
        client.get("/api/status"),
        client.post("/api/ai/check"),
        client.post("/chat", json={"message": "Explique buracos negros"}),
        client.get("/assets/app.js"),
        client.get("/assets/speech.js"),
        client.get("/assets/diagnostics.js"),
        client.get("/assets/app.css"),
        client.get("/assets/index.html"),
    ]
    for response in responses:
        assert SENTINEL not in response.text
    with client.websocket_connect("/ws/status") as ws:
        assert SENTINEL not in ws.receive_text()


def test_frontend_files_do_not_mention_the_key_variable() -> None:
    for path in (p for p in Path("frontend").glob("*") if p.is_file()):
        assert "GEMINI_API_KEY" not in path.read_text(encoding="utf-8").replace(
            "Verifique GEMINI_API_KEY no .env", ""
        ), path


def test_no_audio_is_recorded_or_stored() -> None:
    """Sem MediaRecorder/Blob de áudio no frontend e sem gravação em disco ou libs de áudio no backend."""
    frontend = "".join(p.read_text(encoding="utf-8") for p in Path("frontend").glob("*.js"))
    for forbidden in ("MediaRecorder", "createMediaStreamDestination", "FormData", "audio/webm"):
        assert forbidden not in frontend
    for path in Path("backend").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        forbidden_words = ["pyaudio", "sounddevice", "wave.open", ".write_bytes", "UploadFile", "soundfile"]
        if "knowledge" not in path.parts:  # a base de conhecimento lê/grava apenas JSON institucional
            forbidden_words.append("open(")
        for forbidden in forbidden_words:
            assert forbidden not in text, (path, forbidden)


def test_microphone_is_released_after_diagnostic_capture() -> None:
    js = Path("frontend/diagnostics.js").read_text(encoding="utf-8")
    assert "getTracks().forEach((track) => track.stop())" in js


def test_no_facial_recognition() -> None:
    for path in [p for p in Path("frontend").glob("*") if p.is_file()] + list(Path("backend").rglob("*.py")):
        text = path.read_text(encoding="utf-8").lower()
        assert "facedetector" not in text and "face-api" not in text and "getusermedia({ video" not in text


def test_env_file_is_ignored_by_git() -> None:
    lines = Path(".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in lines and ".venv/" in lines


def test_app_starts_without_gemini_key(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "")
    from backend.config import load_settings

    assert load_settings().gemini_api_key == ""
    assert client.get("/health").status_code == 200


class _BrokenClient:
    """Cliente que simula internet fora do ar."""

    class models:  # noqa: N801
        @staticmethod
        def get(**_):
            import httpx

            raise httpx.ConnectError("sem internet")

        generate_content = get
