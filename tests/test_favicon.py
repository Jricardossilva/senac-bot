"""Favicon do SENAC BOT: arquivos gerados, referências no HTML e rota de compatibilidade /favicon.ico."""
import struct
import zlib
from pathlib import Path

from fastapi.testclient import TestClient

import backend.main as main

BRAND = Path("frontend/brand")
HTML = Path("frontend/index.html").read_text(encoding="utf-8")
client = TestClient(main.app)


def png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def test_favicon_files_exist_with_the_expected_sizes() -> None:
    assert (BRAND / "favicon.svg").exists()
    assert (BRAND / "favicon.ico").exists()
    for size in (16, 32, 48, 180, 192, 512):
        assert png_size(BRAND / f"favicon-{size}.png") == (size, size)


def test_favicons_use_only_the_institutional_palette() -> None:
    svg = (BRAND / "favicon.svg").read_text(encoding="utf-8").lower()
    for color in ("#1366bd", "#083e7d", "#ff7a12", "#ffffff", "#0b3468", "#4fc3ff"):
        assert color in svg
    # nenhuma cor fora da paleta azul/branco/laranja do projeto
    assert not any(bad in svg for bad in ("#ff0000", "#00ff00", "purple", "pink"))


def test_png_favicons_are_rgba_with_transparency_outside_the_tile() -> None:
    data = (BRAND / "favicon-512.png").read_bytes()
    width, height, bit_depth, color_type = struct.unpack(">IIBB", data[16:26])
    assert (width, height, bit_depth, color_type) == (512, 512, 8, 6)  # 6 = RGBA
    idat_start = data.index(b"IDAT") + 4
    length = struct.unpack(">I", data[idat_start - 8 : idat_start - 4])[0]
    raw = zlib.decompress(data[idat_start : idat_start + length])
    stride = 1 + width * 4
    row0 = raw[:stride]
    assert row0[0] == 0  # sem filtro de linha
    corner_alpha = row0[1 + 3]  # canal alfa do primeiro pixel (canto, fora da forma arredondada)
    assert corner_alpha == 0


def test_html_references_the_favicon_in_every_required_form() -> None:
    assert '<link rel="icon" type="image/svg+xml" href="/assets/brand/favicon.svg">' in HTML
    assert 'sizes="32x32" href="/assets/brand/favicon-32.png"' in HTML
    assert 'sizes="16x16" href="/assets/brand/favicon-16.png"' in HTML
    assert '<link rel="shortcut icon" href="/assets/brand/favicon.ico">' in HTML
    assert 'rel="apple-touch-icon" sizes="180x180" href="/assets/brand/favicon-180.png"' in HTML
    assert 'sizes="192x192" href="/assets/brand/favicon-192.png"' in HTML
    assert HTML.count('rel="icon"') >= 4  # svg + 16 + 32 + 192 (não conta o shortcut/apple-touch)


def test_no_emoji_is_used_as_favicon() -> None:
    head = HTML[: HTML.index("</head>")]
    assert "📱" not in head and "🤖" not in head and "data:image/svg+xml,<svg" not in head.replace(" ", "")


def test_favicon_assets_are_served_and_have_the_right_content_type() -> None:
    svg = client.get("/assets/brand/favicon.svg")
    assert svg.status_code == 200 and "svg" in svg.headers["content-type"]
    png = client.get("/assets/brand/favicon-32.png")
    assert png.status_code == 200 and png.headers["content-type"] == "image/png"


def test_favicon_ico_is_served_at_the_domain_root_as_a_fallback() -> None:
    resp = client.get("/favicon.ico")
    assert resp.status_code == 200
    assert resp.headers["content-type"] in ("image/x-icon", "image/vnd.microsoft.icon")
    assert resp.content[:4] == b"\x00\x00\x01\x00"  # assinatura do formato ICO


def test_favicon_does_not_touch_layout_colors_or_existing_functionality() -> None:
    css_before_markers = ["--blue-700", "--orange", ".visitor-view", ".module-card"]
    css = Path("frontend/app.css").read_text(encoding="utf-8")
    assert all(marker in css for marker in css_before_markers)
    assert client.get("/").status_code == 200
