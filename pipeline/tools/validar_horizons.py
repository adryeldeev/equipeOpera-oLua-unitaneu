"""Confere gerar_ceu contra a API Horizons (JPL). FORA do pytest e do site.

    python pipeline/tools/validar_horizons.py

Para 3 locais e 6 instantes, pede ao Horizons o azimute/elevação aparentes
(quantidade 4) e a distância (quantidade 20) do Sol (10) e da Terra (399),
com observador na superfície lunar, e compara com pipeline.ephemeris.

Parâmetros do Horizons (conferidos na documentação da API e no manual):
- CENTER='coord@301' + COORD_TYPE='GEODETIC' + SITE_COORD='lon,lat,alt_km'
  (lon LESTE positiva para a Lua; coordenadas no "mean Earth" do DE421).
  A string 'coord@301' não aparece literalmente na doc da API (segue o
  padrão site@corpo do manual); confirmada pelo cabeçalho da resposta
  ("user defined site", coordenadas ecoadas, raios 1737,4 km esféricos).
  O Horizons usa DE441; nós, DE440 (diferença desprezível em 2027).
- AZ medido a partir do Norte, sentido horário; EL relativa ao plano
  perpendicular à vertical local. Sem refração fora da Terra.
- TLIST com datas em UT (TIME_TYPE padrão das tabelas de observador).

Uso responsável: requisições SEQUENCIAIS, pausa entre elas, poucas novas
tentativas e cache da resposta bruta em cache/horizons/ (rodar de novo não
gera tráfego). Só serve para validar; nunca para gerar os dados.
"""

import hashlib
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))

from pipeline.ephemeris import carregar_recursos, gerar_ceu  # noqa: E402

API = "https://ssd.jpl.nasa.gov/api/horizons.api"
CACHE = RAIZ / "cache" / "horizons"
PAUSA_S = 1.5
TENTATIVAS = 3
TOLERANCIA_DEG = 0.05  # inicial; a equipe define a final

SITES = ["shackleton", "malapert", "apollo11"]
INSTANTES = [datetime(2027, 1, 1, 0, 0), datetime(2027, 2, 15, 6, 0),
             datetime(2027, 4, 1, 12, 0), datetime(2027, 6, 10, 18, 0),
             datetime(2027, 9, 1, 3, 0), datetime(2027, 12, 20, 21, 0)]
CORPOS = {"sun": ("10", 696_000.0), "earth": ("399", 6_378.0)}


def consultar(site, comando):
    """Texto bruto do Horizons, usando cache em disco."""
    lon = site["lon"] % 360  # Horizons aceita 0..360 a leste
    params = {
        "format": "text",
        "COMMAND": f"'{comando}'",
        "OBJ_DATA": "'NO'",
        "MAKE_EPHEM": "'YES'",
        "EPHEM_TYPE": "'OBSERVER'",
        "CENTER": "'coord@301'",
        "COORD_TYPE": "'GEODETIC'",
        "SITE_COORD": f"'{lon:.6f},{site['lat']:.6f},0'",
        "TLIST": " ".join(f"'{t:%Y-%m-%d %H:%M}'" for t in INSTANTES),
        "QUANTITIES": "'4,20'",
        "ANG_FORMAT": "'DEG'",
        "CSV_FORMAT": "'YES'",
        "EXTRA_PREC": "'YES'",
        "RANGE_UNITS": "'KM'",
        "APPARENT": "'AIRLESS'",
    }
    chave = hashlib.sha1(repr(sorted(params.items())).encode()).hexdigest()[:16]
    arq = CACHE / f"{site['id']}_{comando}_{chave}.txt"
    if arq.exists():
        return arq.read_text(encoding="utf-8")

    for tentativa in range(1, TENTATIVAS + 1):
        try:
            time.sleep(PAUSA_S)
            r = requests.get(API, params=params, timeout=60)
            r.raise_for_status()
            if "$$SOE" not in r.text:
                raise RuntimeError("resposta sem tabela ($$SOE):\n" + r.text[:1500])
            CACHE.mkdir(parents=True, exist_ok=True)
            arq.write_text(r.text, encoding="utf-8")
            return r.text
        except (requests.RequestException, RuntimeError) as e:
            print(f"  tentativa {tentativa}/{TENTATIVAS} falhou: {e}")
            if tentativa == TENTATIVAS:
                raise
            time.sleep(PAUSA_S * 2 ** tentativa)


def interpretar(texto):
    """Lista de (az, el, delta_km) na ordem de TLIST, e linhas úteis do cabeçalho."""
    linhas = texto.splitlines()
    i0 = linhas.index("$$SOE")
    i1 = linhas.index("$$EOE")
    cab = [c.strip() for c in linhas[i0 - 2].split(",")]  # linha de nomes de coluna
    iaz = next(i for i, c in enumerate(cab) if c.startswith("Azi"))
    iel = next(i for i, c in enumerate(cab) if c.startswith("Elev"))
    idl = next(i for i, c in enumerate(cab) if c == "delta")
    dados = []
    for ln in linhas[i0 + 1:i1]:
        c = [x.strip() for x in ln.split(",")]
        dados.append((float(c[iaz]), float(c[iel]), float(c[idl])))
    info = [ln.strip() for ln in linhas[:i0]
            if ln.startswith(("Center geodetic", "Center cylindric", "Center radii",
                              "Center-site name", "Center body name", "Target body name"))]
    return dados, info


def dif_ang(a, b):
    return (a - b + 180) % 360 - 180


def main():
    carregar_recursos()
    with open(RAIZ / "pipeline" / "config" / "sites.yaml", encoding="utf-8") as f:
        todos = {s["id"]: s for s in yaml.safe_load(f)["sites"]}

    piores = {}
    for sid in SITES:
        site = todos[sid]
        print(f"\n=== {site['name']} (lat {site['lat']}, lon {site['lon']}) ===")
        for corpo, (comando, raio) in CORPOS.items():
            dados, info = interpretar(consultar(site, comando))
            if corpo == "sun":
                for ln in info:
                    print(f"  Horizons | {ln}")
            print(f"  {corpo:5}  instante (UTC)      dAz(°)    dEl(°)   dRaio(°)   el")
            for t, (az_h, el_h, d_h) in zip(INSTANTES, dados):
                c = gerar_ceu(site, t.replace(tzinfo=timezone.utc), 1 / 1440, 1)[corpo]
                daz = dif_ang(c["az"][0], az_h)
                d_el = c["el"][0] - el_h
                drad = c["rad_deg"][0] - math.degrees(math.asin(raio / d_h))
                # Perto do zênite o azimute é instável; vale a separação angular.
                daz_efetivo = daz * math.cos(math.radians(el_h))
                for k, v in (("az", abs(daz_efetivo)), ("el", abs(d_el)), ("rad", abs(drad))):
                    piores[(corpo, k)] = max(piores.get((corpo, k), 0.0), v)
                print(f"         {t:%Y-%m-%d %H:%M}  {daz:+9.5f} {d_el:+9.5f} {drad:+10.6f}  {el_h:7.3f}")

    print("\n=== Pior diferença (|dAz|·cos(el), |dEl|, |dRaio|) ===")
    ok = True
    for (corpo, k), v in sorted(piores.items()):
        passa = v <= TOLERANCIA_DEG
        ok &= passa
        print(f"  {corpo:5} {k:3}: {v:.5f}°  {'ok' if passa else 'ACIMA'} da tolerância de {TOLERANCIA_DEG}°")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
