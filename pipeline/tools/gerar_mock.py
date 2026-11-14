"""Gera dados FALSOS (mock) em data/, seguindo o contrato de dados.

Serve para desenvolver o frontend antes do pipeline real existir.
Usa só a biblioteca padrão + pyyaml. Reprodutível (semente fixa).

    python pipeline/tools/gerar_mock.py

Saída:
    data/sites.json
    data/horizon/<id>.json
    data/sky/<id>.json
Todo JSON leva "mock": true (em sites.json, em cada item da lista).

NADA aqui é efeméride real: as fórmulas só imitam o comportamento
qualitativo (Sol rasante no polo, Terra quase parada no céu).
"""

import json
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

# Raiz do repositório: pipeline/tools/gerar_mock.py -> ../../
ROOT = Path(__file__).resolve().parents[2]
SITES_YAML = ROOT / "pipeline" / "config" / "sites.yaml"
DATA = ROOT / "data"

SEED = 42
START = datetime(2027, 1, 1, tzinfo=timezone.utc)
DAYS = 30
STEP_MIN = 60

# Períodos (dias) usados no mock
SYNODIC = 29.53      # dia solar lunar (de um nascer do Sol ao outro)
DRACONIC_YEAR = 346.6  # ciclo da declinação do Sol vista da Lua
LIB_LAT = 27.21      # libração em latitude (aprox. mês draconítico)
LIB_LON = 27.55      # libração em longitude (aprox. mês anomalístico)


def az_el(site_lat, site_lon, sub_lat, sub_lon):
    """Azimute/elevação de um corpo muito distante, dado o ponto sub-corpo.

    Trigonometria esférica clássica (mesma do céu terrestre):
      H   = ângulo horário = lon_local - lon_subcorpo (lon LESTE positiva)
      el  = asin(sin φ sin δ + cos φ cos δ cos H)
      az  = atan2(-cos δ sin H, sin δ cos φ - cos δ sin φ cos H)
    az medido a partir do Norte, no sentido horário (Norte=0, Leste=90).
    Ignora relevo, paralaxe e o tamanho do disco: é só um mock.
    """
    phi = math.radians(site_lat)
    dec = math.radians(sub_lat)
    h = math.radians(site_lon - sub_lon)
    el = math.asin(math.sin(phi) * math.sin(dec)
                   + math.cos(phi) * math.cos(dec) * math.cos(h))
    az = math.atan2(-math.cos(dec) * math.sin(h),
                    math.sin(dec) * math.cos(phi)
                    - math.cos(dec) * math.sin(phi) * math.cos(h))
    return math.degrees(az) % 360.0, math.degrees(el)


def mock_horizon(site, rng):
    """Horizonte falso: ondulado (0 a ~6°) no polo, plano fora dele."""
    if site["category"] != "polo_sul":
        return [0.0] * 360
    # Soma de algumas ondas com fase/amplitude aleatórias (mas reprodutíveis)
    waves = [(rng.randint(1, 6), rng.uniform(0.5, 2.0), rng.uniform(0, 2 * math.pi))
             for _ in range(4)]
    base = rng.uniform(2.0, 3.0)
    out = []
    for az in range(360):
        a = math.radians(az)
        v = base + sum(amp * math.sin(k * a + ph) for k, amp, ph in waves)
        v += rng.uniform(-0.2, 0.2)  # rugosidade
        out.append(round(min(max(v, 0.0), 6.0), 2))
    return out


def mock_sky(site, rng):
    """Séries falsas de Sol e Terra, passo de STEP_MIN, por DAYS dias."""
    n = DAYS * 24 * 60 // STEP_MIN
    sun_phase = rng.uniform(0, 360)
    sun = {"az": [], "el": []}
    earth = {"az": [], "el": []}
    for i in range(n):
        t = i * STEP_MIN / (60 * 24)  # dias desde START
        # Sol: o ponto subsolar dá uma volta para OESTE a cada dia solar
        # lunar; a declinação do Sol oscila só ±1,54° (eixo pouco inclinado).
        # Resultado: no polo o Sol fica rasante; no equador sobe e desce muito.
        sub_lat = 1.54 * math.sin(2 * math.pi * t / DRACONIC_YEAR)
        sub_lon = (sun_phase - 360.0 * t / SYNODIC + 180) % 360 - 180
        az, el = az_el(site["lat"], site["lon"], sub_lat, sub_lon)
        sun["az"].append(round(az, 2))
        sun["el"].append(round(el, 2))
        # Terra: rotação síncrona -> ponto sub-Terra perto de (0°, 0°),
        # oscilando só pela libração (movimento lento, ~±7°).
        e_lat = 6.7 * math.sin(2 * math.pi * t / LIB_LAT)
        e_lon = 7.9 * math.sin(2 * math.pi * t / LIB_LON)
        az, el = az_el(site["lat"], site["lon"], e_lat, e_lon)
        earth["az"].append(round(az, 2))
        earth["el"].append(round(el, 2))
    return {
        "mock": True,
        "site": site["id"],
        "start": START.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "step_min": STEP_MIN,
        "sun": sun,
        "earth": earth,
    }


def write_json(path, obj, pretty=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        if pretty:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        else:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")


def main():
    with open(SITES_YAML, encoding="utf-8") as f:
        sites = yaml.safe_load(f)["sites"]

    keys = ("id", "name", "lat", "lon", "category", "mission")
    write_json(DATA / "sites.json",
               [{**{k: s[k] for k in keys}, "mock": True} for s in sites],
               pretty=True)

    for s in sites:
        # Uma semente por local: mudar a ordem do YAML não altera os dados.
        rng = random.Random(f"{SEED}-{s['id']}")
        write_json(DATA / "horizon" / f"{s['id']}.json", {
            "mock": True,
            "site": s["id"],
            "az_step_deg": 1,
            "horizon_deg": mock_horizon(s, rng),
        })
        write_json(DATA / "sky" / f"{s['id']}.json", mock_sky(s, rng))
        print(f"ok  {s['id']}")

    print(f"Mock gerado em {DATA}")


if __name__ == "__main__":
    main()
