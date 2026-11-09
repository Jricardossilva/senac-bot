"""Coordenadas das unidades e cálculo da unidade mais próxima (backend/knowledge/geo.py)."""
from pathlib import Path

from backend.knowledge.geo import GeoUnit, haversine_km, load_geo, nearest
from backend.knowledge.store import load_json
from tests.kb_helpers import KNOWLEDGE_DIR

JP = GeoUnit("CEP-JP", "João Pessoa", "PB", -7.1189707, -34.8742768, "via", "pb-unidades", "")
CG = GeoUnit("CEP-CG", "Campina Grande", "PB", -7.2048361, -35.8747606, "endereço", "pb-unidades", "")
RECIFE = GeoUnit("RECIFE", "Recife", "PE", -8.0476, -34.8770, "endereço", "pb-unidades", "")


def test_haversine_is_zero_for_the_same_point() -> None:
    assert haversine_km(JP.lat, JP.lon, JP.lat, JP.lon) == 0.0


def test_haversine_matches_the_known_distance_between_joao_pessoa_and_recife() -> None:
    # João Pessoa-Recife: pouco mais de 100 km em linha reta.
    distance = haversine_km(JP.lat, JP.lon, RECIFE.lat, RECIFE.lon)
    assert 95 <= distance <= 115


def test_nearest_orders_by_distance_and_respects_the_limit() -> None:
    # A partir do CEP-CG: ele mesmo é o mais próximo (distância 0); os outros dois vêm ordenados pela distância real.
    ranked = nearest([CG, JP, RECIFE], CG.lat, CG.lon, limit=2)
    assert ranked[0][0].unit == "CEP-CG"
    assert ranked[0][1] == 0.0
    assert ranked[1][1] > 0.0
    assert len(ranked) == 2


def test_load_geo_reads_the_real_file_with_only_units_with_confirmed_address() -> None:
    units = load_geo(KNOWLEDGE_DIR, load_json)
    keys = {u.unit for u in units}
    assert {"CEP-JP", "CEP-CG", "DOM-ULRICO", "CENDEGE"} <= keys
    # Unidades sem endereço confirmado nunca entram no cálculo de proximidade.
    assert "PATOS" not in keys and "TADROS" not in keys and "ZONA-SUL" not in keys


def test_load_geo_tolerates_a_missing_file(tmp_path: Path) -> None:
    assert load_geo(tmp_path, load_json) == []


def test_load_geo_tolerates_invalid_entries(tmp_path: Path) -> None:
    (tmp_path / "geo.json").write_text(
        '{"units": [{"unit": "X", "lat": "nao e numero", "lon": -34}, {"unit": "", "lat": 1, "lon": 1}]}',
        encoding="utf-8",
    )
    assert load_geo(tmp_path, load_json) == []
