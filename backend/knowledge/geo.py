"""Coordenadas das unidades e cálculo da unidade mais próxima (knowledge/geo.json).

Distância em linha reta (fórmula de Haversine), calculada aqui em Python — nunca pelo Gemini. Só entram
unidades com endereço já confirmado na base institucional (ver knowledge/geo.json); as demais ficam de
fora até terem endereço validado, em vez de participar de um cálculo impreciso.
"""
import logging
import math
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("senac_bot.knowledge.geo")

EARTH_RADIUS_KM = 6371.0


@dataclass(frozen=True)
class GeoUnit:
    unit: str
    municipio: str
    uf: str
    lat: float
    lon: float
    precision: str
    source_id: str
    note: str


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def _build_unit(item: dict, errors: list[str]) -> GeoUnit | None:
    unit = str(item.get("unit", "")).strip()
    if not unit:
        errors.append("geo.json: unidade sem id")
        return None
    try:
        lat = float(item["lat"])
        lon = float(item["lon"])
    except (KeyError, TypeError, ValueError):
        errors.append(f"geo.json[{unit}]: lat/lon inválidos")
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        errors.append(f"geo.json[{unit}]: lat/lon fora do intervalo válido")
        return None
    return GeoUnit(
        unit=unit,
        municipio=str(item.get("municipio", "")).strip(),
        uf=str(item.get("uf", "")).strip(),
        lat=lat,
        lon=lon,
        precision=str(item.get("precision", "")).strip(),
        source_id=str(item.get("source_id", "")).strip(),
        note=str(item.get("note", "")).strip(),
    )


def load_geo(directory: Path, load_json) -> list[GeoUnit]:
    """Carrega knowledge/geo.json. Ausente ou inválido nunca derruba a aplicação: só desativa a proximidade."""
    try:
        raw = load_json(directory / "geo.json")
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as error:
        logger.error("geo.json não lido: %s", error)
        return []
    errors: list[str] = []
    units: list[GeoUnit] = []
    seen: set[str] = set()
    for item in raw.get("units", []):
        geo_unit = _build_unit(item, errors)
        if geo_unit is None:
            continue
        if geo_unit.unit in seen:
            errors.append(f"geo.json: unidade duplicada {geo_unit.unit!r}")
            continue
        seen.add(geo_unit.unit)
        units.append(geo_unit)
    for problem in errors:
        logger.error("Coordenadas das unidades: %s", problem)
    return units


def nearest(units: list[GeoUnit], lat: float, lon: float, limit: int = 3) -> list[tuple[GeoUnit, float]]:
    """As `limit` unidades mais próximas de (lat, lon), ordenadas pela menor distância em linha reta."""
    ranked = [(unit, haversine_km(lat, lon, unit.lat, unit.lon)) for unit in units]
    ranked.sort(key=lambda pair: pair[1])
    return ranked[:limit]
