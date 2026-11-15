"""Escolhe pontos de pouso a partir do DEM do LOLA (reprodutível).

Não há coordenadas oficiais públicas dos pontos das regiões candidatas do
Artemis III, só os nomes. Este script deriva pontos com critérios simples
e declarados, para o sites.yaml:

  topo     ponto mais alto do DEM num raio em volta de uma referência
           (ex.: topo do Maciço Malapert)
  borda    ponto com mais horas de Sol num anel em volta da borda de uma
           cratera (0,9 a 1,3 × raio), refinado numa grade local

    python pipeline/tools/escolher_pontos.py

Usa céu real (ephemeris, 2027, passo de 2 h) e horizonte real (horizon).
Imprime os pontos; NÃO altera o sites.yaml sozinho.
"""

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pipeline import ephemeris as ef  # noqa: E402
from pipeline import horizon as hz  # noqa: E402
from pipeline import metrics as m  # noqa: E402

INICIO = datetime(2027, 1, 1, tzinfo=timezone.utc)
DIAS, PASSO_MIN = 365, 120

# Centros de cratera e raio aproximado, CONFERIDOS no DEM (o centro tem de
# ser uma depressão funda em relação ao anel da borda):
#   Shackleton: Wikipedia (-89,67°, 129,78°E); centro ~3,9 km abaixo da borda.
#   Haworth: (-87,45°, -4,14°); centro ~3,2 km abaixo do anel de 25 km. O
#   valor da Wikipedia lido na busca (-86,9°, -4,0°) não bate com o relevo.
CRATERAS = {
    "shackleton": (-89.67, 129.78, 10.5),
    "haworth": (-87.45, -4.14, 25.5),
}
# Referência para o topo: o pico do Malapert fica "quase exatamente em 0° de longitude".
TOPOS = {"malapert": (-86.0, 0.0, 15.0)}


def sol_e_terra(lat, lon, dems):
    s = {"id": "p", "lat": float(lat), "lon": float(lon)}
    ceu = ef.gerar_ceu(s, INICIO, DIAS, PASSO_MIN)
    h = hz.calcular_horizonte(s, dems)
    v = m.visibilidade(ceu, h)
    return float(v["sol_visivel"].mean()), float(v["terra_visivel"].mean())


def topo(lat, lon, raio_km, dems):
    """Centro do pixel mais alto do DEM mais fino numa janela em volta de (lat, lon).

    Usa o pixel (e não uma amostra interpolada) para o ponto ser único: no
    topo estreito do Malapert, 100–200 m de diferença mudam o Sol em ~10 pontos.
    """
    d = dems[0]
    lin, col = (int(round(float(v))) for v in d.pixel(np.array(lat), np.array(lon)))
    w = int(raio_km * 1000 / d.m_por_pixel)
    jan = np.asarray(d.dados[lin - w:lin + w + 1, col - w:col + w + 1])
    i, j = np.unravel_index(jan.argmax(), jan.shape)
    x = (col - w + j - d.off_coluna) * d.m_por_pixel
    y = (d.off_linha - (lin - w + i)) * d.m_por_pixel
    la = np.degrees(2 * np.arctan(np.hypot(x, y) / (2 * hz.R_LUA_M))) - 90
    lo = np.degrees(np.arctan2(x, y))
    return float(la), float(lo), float(jan.max() * d.escala_dn)


def borda(lat, lon, raio_km, dems):
    """Ponto com mais Sol no anel da borda; desempate pela Terra."""
    melhor = None
    for f in (0.9, 1.0, 1.1, 1.2, 1.3):
        for a in range(0, 360, 5):
            la, lo = hz._destino(lat, lon, np.array([float(a)]), np.array([f * raio_km * 1000]))
            sol, terra = sol_e_terra(la[0, 0], lo[0, 0], dems)
            if melhor is None or (sol, terra) > melhor[:2]:
                melhor = (sol, terra, la[0, 0], lo[0, 0])
    # Refino: grade de 5 × 5 com 400 m de espaçamento em volta do melhor.
    _, _, la0, lo0 = melhor
    for dx in range(-2, 3):
        for dy in range(-2, 3):
            if dx == dy == 0:
                continue
            az = np.degrees(np.arctan2(dx, dy))
            la, lo = hz._destino(la0, lo0, np.array([az]), np.array([400.0 * np.hypot(dx, dy)]))
            sol, terra = sol_e_terra(la[0, 0], lo[0, 0], dems)
            if (sol, terra) > melhor[:2]:
                melhor = (sol, terra, la[0, 0], lo[0, 0])
    return melhor


def main():
    ef.carregar_recursos()
    dems = hz.carregar_dems()
    for nome, (lat, lon, r) in TOPOS.items():
        la, lo, h = topo(lat, lon, r, dems)
        sol, terra = sol_e_terra(la, lo, dems)
        print(f"topo  {nome:11} lat {la:.4f}  lon {lo:.4f}  altura {h:.0f} m  "
              f"Sol {sol:.1%}  Terra {terra:.1%}")
    for nome, (lat, lon, r) in CRATERAS.items():
        t0 = time.perf_counter()
        sol, terra, la, lo = borda(lat, lon, r, dems)
        print(f"borda {nome:11} lat {la:.4f}  lon {lo:.4f}  Sol {sol:.1%}  Terra {terra:.1%}  "
              f"({time.perf_counter() - t0:.0f} s)")


if __name__ == "__main__":
    main()
