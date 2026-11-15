"""Horizonte do terreno a partir dos DEMs polares do LOLA.

Uso como BIBLIOTECA:

    from pipeline.horizon import carregar_dems, calcular_horizonte
    dems = carregar_dems()                         # baixa para cache/lola/ na 1ª vez
    hz = calcular_horizonte(site, dems)            # {site, az_step_deg, horizon_deg[360], meta, mock}

CLI (grava data/horizon/<id>.json de forma atômica):

    python -m pipeline.horizon --out data/horizon
    python -m pipeline.horizon --out data/horizon --site malapert

DEMs (PDS Geosciences Node, LRO LOLA GDR polar, inteiros de 16 bits):
    LDEM_80S_80M   80 m/pixel, de -90° a -80°   (relevo próximo, ~115 MB)
    LDEM_75S_240M 240 m/pixel, de -90° a -75°   (relevo distante, ~29 MB)
Altura = DN × 0,5 m, relativa à esfera de 1.737.400 m. Referencial "Mean
Earth/Polar Axis of DE421", o mesmo MOON_ME do ephemeris.py.

Projeção estereográfica polar sul (esférica, R = 1.737.400 m):
    ρ = 2R·tan(45° + lat/2);  x = ρ·sen(lon);  y = ρ·cos(lon)
    coluna = SAMPLE_PROJECTION_OFFSET + x/MAP_SCALE   (0-based)
    linha  = LINE_PROJECTION_OFFSET   − y/MAP_SCALE   (0-based)
Os sinais foram CONFERIDOS com os dados: só essa orientação põe os centros
de Shackleton, Haworth, Nobile, Cabeus, de Gerlache e Faustini em
depressões (1 a 4 km abaixo da borda). Ver tests/test_horizon.py.

Cálculo (por local):
- Para cada azimute (0 = Norte, horário), anda pelo círculo máximo a partir
  do local. O azimute é do plano tangente local; usar o círculo máximo já
  faz a "rotação pela longitude" que a grade estereográfica exigiria.
- Em cada ponto, altura do DEM mais fino disponível (interpolação bilinear).
- Elevação EXATA na esfera (inclui a curvatura, sem aproximar d²/2R):
      θ = d/R;  r1 = R + h_local + altura_observador;  r2 = R + h_ponto
      elev = atan2(r2·cos θ − r1, r2·sen θ)
- horizon_deg[i] = maior elevação ao longo do raio do azimute i.

Só cobre locais abaixo de -75° de latitude. Fora disso (Apollo 11) a CLI
não grava nada e o horizonte mock continua valendo.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parents[1]
CACHE_LOLA = RAIZ / "cache" / "lola"
URL_PDS = ("https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/"
           "lrolol_1xxx/data/lola_gdr/polar/img/")
# Do mais fino para o mais grosso: cada ponto usa o primeiro que o cobre.
PRODUTOS = ("ldem_80s_80m", "ldem_75s_240m")

R_LUA_M = 1_737_400.0
# TODO(equipe): altura do observador (antena/painel acima do solo). 2 m é
# uma suposição; com 0 m o horizonte fica dominado pelo pixel vizinho.
ALTURA_OBSERVADOR_M = 2.0
DIST_MAX_M = 300_000.0
# Além de ~250 km a queda da curvatura (d²/2R ≈ 18 km) supera qualquer
# desnível do polo sul (~ ±7 km): o relevo já não sobe acima do horizonte.
# Amostragem ao longo do raio: fina perto (onde o ângulo muda rápido).
TRECHOS_M = ((40.0, 20_000.0, 40.0), (20_000.0, 100_000.0, 80.0),
             (100_000.0, DIST_MAX_M, 240.0))


# ---------------------------------------------------------------- DEM

@dataclass(frozen=True)
class Dem:
    nome: str
    dados: np.ndarray          # int16 (memmap), linhas × colunas
    escala_dn: float           # DN × escala_dn = altura (m)
    m_por_pixel: float
    off_linha: float
    off_coluna: float
    lat_max: float             # borda do mapa (ex.: -80)

    def pixel(self, lat, lon):
        """(linha, coluna) 0-based, contínuas, de lat/lon em graus."""
        rho = 2 * R_LUA_M * np.tan(np.pi / 4 + np.radians(lat) / 2)
        lon = np.radians(lon)
        x = rho * np.sin(lon)
        y = rho * np.cos(lon)
        return self.off_linha - y / self.m_por_pixel, self.off_coluna + x / self.m_por_pixel

    def altura(self, lat, lon) -> np.ndarray:
        """Altura (m) com interpolação bilinear; NaN fora do mapa."""
        lin, col = self.pixel(np.asarray(lat, float), np.asarray(lon, float))
        n_lin, n_col = self.dados.shape
        dentro = (lin >= 0) & (lin <= n_lin - 1) & (col >= 0) & (col <= n_col - 1)
        saida = np.full(lin.shape, np.nan)
        if not dentro.any():
            return saida
        l, c = lin[dentro], col[dentro]
        l0 = np.minimum(np.floor(l).astype(np.int64), n_lin - 2)
        c0 = np.minimum(np.floor(c).astype(np.int64), n_col - 2)
        fl, fc = l - l0, c - c0
        d = self.dados
        v = (d[l0, c0] * (1 - fl) * (1 - fc) + d[l0, c0 + 1] * (1 - fl) * fc
             + d[l0 + 1, c0] * fl * (1 - fc) + d[l0 + 1, c0 + 1] * fl * fc)
        saida[dentro] = v * self.escala_dn
        return saida


def _rotulo(caminho: Path) -> dict:
    """Lê as chaves KEY = VALOR de um rótulo PDS3 (só as que usamos)."""
    texto = caminho.read_text(encoding="latin-1")
    chaves = {}
    for k in ("LINES", "LINE_SAMPLES", "SAMPLE_TYPE", "SAMPLE_BITS", "SCALING_FACTOR",
              "OFFSET", "MAP_PROJECTION_TYPE", "CENTER_LATITUDE", "CENTER_LONGITUDE",
              "MAP_SCALE", "LINE_PROJECTION_OFFSET", "SAMPLE_PROJECTION_OFFSET",
              "MAXIMUM_LATITUDE", "A_AXIS_RADIUS", "MAP_PROJECTION_ROTATION"):
        m = re.search(rf"^\s*{k}\s*=\s*\"?([^\"<\r\n]+?)\"?\s*(<[^>]*>)?\s*$", texto, re.M)
        if m:
            chaves[k] = m.group(1).strip()
    return chaves


def abrir_dem(caminho_img: Path) -> Dem:
    """Abre um .img do LOLA (com o .lbl ao lado) e confere o rótulo."""
    caminho_img = Path(caminho_img)
    r = _rotulo(caminho_img.with_suffix(".lbl"))
    esperado = {"SAMPLE_TYPE": "LSB_INTEGER", "SAMPLE_BITS": "16",
                "MAP_PROJECTION_TYPE": "POLAR STEREOGRAPHIC", "CENTER_LATITUDE": "-90",
                "CENTER_LONGITUDE": "0", "MAP_PROJECTION_ROTATION": "0.0"}
    for k, v in esperado.items():
        if r.get(k) != v:
            raise ValueError(f"{caminho_img.name}: rótulo com {k} = {r.get(k)!r} (esperado {v!r})")
    if not math.isclose(float(r["A_AXIS_RADIUS"]) * 1000, R_LUA_M) or \
            not math.isclose(float(r["OFFSET"]), R_LUA_M):
        raise ValueError(f"{caminho_img.name}: raio de referência diferente de {R_LUA_M} m")
    n_lin, n_col = int(r["LINES"]), int(r["LINE_SAMPLES"])
    if caminho_img.stat().st_size != n_lin * n_col * 2:
        raise ValueError(f"{caminho_img.name}: tamanho não bate com {n_lin}×{n_col} (download incompleto?)")
    return Dem(
        nome=caminho_img.stem.upper(),
        dados=np.memmap(caminho_img, dtype="<i2", mode="r", shape=(n_lin, n_col)),
        escala_dn=float(r["SCALING_FACTOR"]),
        m_por_pixel=float(r["MAP_SCALE"]),
        off_linha=float(r["LINE_PROJECTION_OFFSET"]),
        off_coluna=float(r["SAMPLE_PROJECTION_OFFSET"]),
        lat_max=float(r["MAXIMUM_LATITUDE"]),
    )


def carregar_dems(cache_dir: str | Path | None = None, baixar: bool = True) -> list[Dem]:
    """DEMs de PRODUTOS (do mais fino ao mais grosso), baixando o que faltar."""
    cache = Path(cache_dir) if cache_dir else CACHE_LOLA
    faltando = [f"{p}{ext}" for p in PRODUTOS for ext in (".lbl", ".img")
                if not (cache / f"{p}{ext}").exists()]
    if faltando and not baixar:
        raise FileNotFoundError(f"DEMs ausentes em {cache}: {', '.join(faltando)}")
    if faltando:
        _baixar(cache, faltando)
    return [abrir_dem(cache / f"{p}.img") for p in PRODUTOS]


def _baixar(cache: Path, arquivos):
    import shutil
    import urllib.request

    cache.mkdir(parents=True, exist_ok=True)
    for nome in arquivos:
        destino = cache / nome
        tmp = destino.with_name(destino.name + ".part")
        print(f"baixando {URL_PDS + nome} ...")
        with urllib.request.urlopen(URL_PDS + nome, timeout=60) as resp, open(tmp, "wb") as f:
            shutil.copyfileobj(resp, f, length=1 << 20)
        tmp.replace(destino)


# ---------------------------------------------------------------- horizonte

def distancias_m() -> np.ndarray:
    return np.concatenate([np.arange(a, b, passo) for a, b, passo in TRECHOS_M])


def _destino(lat, lon, az, d):
    """Ponto a distância d (m) no azimute az a partir de (lat, lon), na esfera."""
    f1, l1 = np.radians(lat), np.radians(lon)
    az = np.radians(az)[:, None]
    t = (np.asarray(d) / R_LUA_M)[None, :]
    f2 = np.arcsin(np.sin(f1) * np.cos(t) + np.cos(f1) * np.sin(t) * np.cos(az))
    l2 = l1 + np.arctan2(np.sin(az) * np.sin(t) * np.cos(f1), np.cos(t) - np.sin(f1) * np.sin(f2))
    return np.degrees(f2), (np.degrees(l2) + 180.0) % 360.0 - 180.0


def _altura(dems, lat, lon):
    """Altura do DEM mais fino que cobre cada ponto (NaN se nenhum)."""
    h = np.full(np.shape(lat), np.nan)
    for dem in dems:
        falta = np.isnan(h)
        if not falta.any():
            break
        h[falta] = dem.altura(lat[falta], lon[falta])
    return h


def elevacao_graus(h_obs, h_ponto, d):
    """Elevação exata (graus) de um ponto do relevo a distância d (m) na esfera."""
    t = np.asarray(d) / R_LUA_M
    r1 = R_LUA_M + h_obs
    r2 = R_LUA_M + h_ponto
    return np.degrees(np.arctan2(r2 * np.cos(t) - r1, r2 * np.sin(t)))


def calcular_horizonte(site: dict, dems: list[Dem], az_step_deg: float = 1.0,
                       altura_observador_m: float = ALTURA_OBSERVADOR_M) -> dict:
    """Horizonte do local no formato do contrato (com "mock": false)."""
    lat, lon = float(site["lat"]), float(site["lon"])
    h_local = _altura(dems, np.array([lat]), np.array([lon]))[0]
    if np.isnan(h_local):
        raise ValueError(f"{site['id']} ({lat}, {lon}) está fora da cobertura dos DEMs "
                         f"(até {max(d.lat_max for d in dems)}°)")
    n = int(round(360 / az_step_deg))
    az = np.arange(n) * az_step_deg
    d = distancias_m()
    la, lo = _destino(lat, lon, az, d)
    h = _altura(dems, la, lo)
    elev = elevacao_graus(h_local + altura_observador_m, h, d[None, :])
    coberto = ~np.isnan(h)
    if not coberto.any(axis=1).all():
        raise ValueError(f"{site['id']}: algum azimute sem nenhum ponto de relevo")
    horiz = np.nanmax(elev, axis=1)
    # Distância até onde o raio teve dado (o resto saiu do mapa).
    alcance = np.where(coberto, d[None, :], 0).max(axis=1)
    return {
        "site": site["id"],
        "az_step_deg": az_step_deg,
        "horizon_deg": (np.round(horiz, 3) + 0.0).tolist(),
        "meta": {
            "fonte": "LOLA GDR polar (PDS Geosciences Node)",
            "dems": [f"{x.nome} ({x.m_por_pixel:g} m/pixel)" for x in dems],
            "altura_local_m": round(float(h_local), 1),
            "altura_observador_m": altura_observador_m,
            "dist_max_m": float(d[-1]),
            "alcance_min_m": float(alcance.min()),
            "lat": lat, "lon": lon,
            "gerado_em": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "mock": False,
    }


# ---------------------------------------------------------------- CLI

def main(argv=None) -> int:
    import argparse
    import sys
    import time

    import yaml

    from pipeline.export import gravar_json_atomico, validar_horizonte

    p = argparse.ArgumentParser(prog="python -m pipeline.horizon",
                                description="Gera data/horizon/<id>.json a partir do LOLA.")
    p.add_argument("--sites", default=str(RAIZ / "pipeline" / "config" / "sites.yaml"))
    p.add_argument("--out", default=str(RAIZ / "data" / "horizon"))
    p.add_argument("--site", help="gera só este id")
    p.add_argument("--altura-observador", type=float, default=ALTURA_OBSERVADOR_M)
    a = p.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    with open(a.sites, encoding="utf-8") as f:
        sites = yaml.safe_load(f)["sites"]
    if a.site:
        sites = [s for s in sites if s["id"] == a.site]
        if not sites:
            p.error(f"site '{a.site}' não está em {a.sites}")

    dems = carregar_dems()
    lat_cobertura = max(d.lat_max for d in dems)
    erros = 0
    for s in sites:
        if s["lat"] > lat_cobertura:
            print(f"pula {s['id']:12} lat {s['lat']} fora dos DEMs polares (mantém o arquivo atual)")
            continue
        t0 = time.perf_counter()
        hz = calcular_horizonte(s, dems, altura_observador_m=a.altura_observador)
        problemas = validar_horizonte(hz)
        if problemas:
            print(f"ERRO {s['id']}: {'; '.join(problemas)}")
            erros += 1
            continue
        gravar_json_atomico(Path(a.out) / f"{s['id']}.json", hz, compacto=True)
        h = hz["horizon_deg"]
        print(f"ok   {s['id']:12} min {min(h):6.2f}°  máx {max(h):6.2f}°  "
              f"alcance mín {hz['meta']['alcance_min_m'] / 1000:.0f} km  {time.perf_counter() - t0:.2f} s")
    return 1 if erros else 0


if __name__ == "__main__":
    raise SystemExit(main())
