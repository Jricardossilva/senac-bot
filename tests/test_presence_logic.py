"""Lógica de presença da câmera (frontend/presence-logic.js), testada com o executor de testes do Node."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js não está instalado (só necessário para este teste)")
def test_presence_logic_with_node() -> None:
    result = subprocess.run(
        ["node", "--test", str(ROOT / "tests" / "presence_logic.test.mjs")],
        capture_output=True, text=True, timeout=60, cwd=ROOT, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_vendored_face_detector_files_are_present_and_served() -> None:
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    for name, mime in (
        ("vision_bundle.mjs", "javascript"),
        ("vision_wasm_internal.js", "javascript"),
        ("vision_wasm_internal.wasm", "application/wasm"),
        ("blaze_face_short_range.tflite", ""),
    ):
        response = client.get(f"/assets/vendor/mediapipe/{name}")
        assert response.status_code == 200, name
        assert mime in response.headers["content-type"], (name, response.headers["content-type"])
        assert len(response.content) > 1000, name


def test_interface_files_are_always_revalidated_by_the_browser() -> None:
    from fastapi.testclient import TestClient

    from backend.main import app

    response = TestClient(app).get("/assets/app.js")
    assert response.status_code == 200 and response.headers["cache-control"] == "no-cache"
    assert response.headers.get("etag")  # permite resposta 304 sem baixar de novo
