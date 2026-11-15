"""Gera as texturas da Lua 3D do front (web/assets/).

    python pipeline/tools/gerar_texturas_lua.py

Saída:
  polo_sul_normal.jpg  mapa de normais em ESPAÇO DE OBJETO da calota sul
                       (-80° a -90°), a partir do LDEM_80S_80M (o mesmo DEM do
                       horizonte). Com a luz na direção real do Sol, o relevo
                       aparece sombreado como está naquele instante.
  polo_sul_cor.png     cor (cinza) + alfa: a calota some suavemente entre -81° e -80°
                       para emendar no mapa global.

Grade: estereográfica polar, a mesma do DEM (950 × 950 pixels de 640 m;
média de blocos de 8 × 8). No front, a calota usa UV:
    u = (x + L) / 2L,  v = (y + L) / 2L,  L = 304.000 m
    x = ρ·sen(lon), y = ρ·cos(lon), ρ = 2R·tan(45° + lat/2)

Eixos do Three.js no front: X = ME x (lon 0°), Y = ME z (norte), Z = −ME y.

As texturas globais (lroc_color_2k.jpg e ldem_3_8bit.jpg) vêm do NASA SVS
CGI Moon Kit (https://svs.gsfc.nasa.gov/4720) e são só copiadas.

Precisa de pillow (só para esta ferramenta): pip install pillow
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pipeline import horizon as hz  # noqa: E402

RAIZ = Path(__file__).resolve().parents[2]
SAIDA = RAIZ / "web" / "assets"
BLOCO = 8                 # 7600 / 8 = 950 pixels de 640 m
EXAGERO = 2.0             # exagero vertical só para o relevo ficar legível
LAT_BORDA = -80.0         # borda do DEM
LAT_CHEIA = -81.0         # a partir daqui a calota é opaca
COR_CINZA = (150, 147, 142)  # tom médio das terras altas no lroc_color_2k (perto de -75°)


def main():
    from PIL import Image

    dem = hz.carregar_dems(baixar=True)[0]
    n = dem.dados.shape[0] // BLOCO
    h = np.asarray(dem.dados[: n * BLOCO, : n * BLOCO], dtype=np.float32)
    h = h.reshape(n, BLOCO, n, BLOCO).mean(axis=(1, 3)) * dem.escala_dn  # metros
    passo = dem.m_por_pixel * BLOCO
    meia = n * passo / 2

    # Centro de cada pixel na grade estereográfica (linha 0 = +y, em cima).
    c = (np.arange(n) + 0.5) * passo - meia
    x, y = np.meshgrid(c, -c)
    rho = np.hypot(x, y)
    lat = np.radians(2 * np.degrees(np.arctan(rho / (2 * hz.R_LUA_M))) - 90)
    lon = np.arctan2(x, y)

    # Gradiente da altura no plano (m/m): colunas = +x, linhas = −y.
    dh_dlin, dh_dcol = np.gradient(h * EXAGERO, passo)
    gx, gy = dh_dcol, -dh_dlin
    # Leste = (cos lon, −sen lon) e Norte = (sen lon, cos lon) no plano (x, y).
    g_leste = gx * np.cos(lon) - gy * np.sin(lon)
    g_norte = gx * np.sin(lon) + gy * np.cos(lon)

    sf, cf, sl, cl = np.sin(lat), np.cos(lat), np.sin(lon), np.cos(lon)
    E = np.stack([-sl, cl, np.zeros_like(sl)])
    N = np.stack([-sf * cl, -sf * sl, cf])
    U = np.stack([cf * cl, cf * sl, sf])
    nrm = U - g_leste * E - g_norte * N          # normal em coordenadas ME
    nrm /= np.linalg.norm(nrm, axis=0)
    tres = np.stack([nrm[0], nrm[2], -nrm[1]])   # ME -> eixos do Three.js
    rgb = np.clip((tres + 1) * 127.5, 0, 255).astype(np.uint8).transpose(1, 2, 0)

    lat_g = np.degrees(lat)
    alfa = np.clip((LAT_BORDA - lat_g) / (LAT_BORDA - LAT_CHEIA), 0, 1)
    cor = np.empty((n, n, 4), dtype=np.uint8)
    cor[..., :3] = COR_CINZA
    cor[..., 3] = (alfa * 255).astype(np.uint8)

    SAIDA.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgb, "RGB").save(SAIDA / "polo_sul_normal.jpg", quality=90)
    Image.fromarray(cor, "RGBA").save(SAIDA / "polo_sul_cor.png", optimize=True)
    print(f"ok  {n}x{n} pixels de {passo:.0f} m, meia-largura {meia:.0f} m, exagero {EXAGERO}x")
    for f in ("polo_sul_normal.jpg", "polo_sul_cor.png"):
        print(f"    {f}: {(SAIDA / f).stat().st_size / 1e3:.0f} KB")


if __name__ == "__main__":
    main()
