"""Testes de pipeline/horizon.py. Sem rede.

Os testes sintéticos não precisam dos DEMs. Os que usam o LOLA real são
pulados se cache/lola/ não tiver os arquivos (rode a CLI uma vez).

    python -m pytest pipeline/tests/test_horizon.py -v
"""

import json
from pathlib import Path

import numpy as np
import pytest

from pipeline import horizon as hz
from pipeline.export import validar_horizonte

RAIZ = Path(__file__).resolve().parents[2]
POLARES = ["shackleton", "malapert", "nobile", "haworth", "mons_mouton"]


# ---------------------------------------------------------------- sintéticos

def dem_sintetico(alturas_m, m_por_pixel=80.0):
    """DEM quadrado centrado no polo, com a mesma projeção do LOLA."""
    n = alturas_m.shape[0]
    centro = (n - 1) / 2
    return hz.Dem(nome="SINTETICO", dados=np.asarray(alturas_m * 2, dtype=np.int16),
                  escala_dn=0.5, m_por_pixel=m_por_pixel, off_linha=centro,
                  off_coluna=centro, lat_max=-80.0)


def test_projecao_ida_e_volta():
    dem = dem_sintetico(np.zeros((101, 101)))
    # O polo cai no centro; lon 0 fica "para cima" (linha menor), lon 90 à direita.
    assert dem.pixel(np.array(-90.0), np.array(0.0)) == pytest.approx((50, 50))
    lin, col = dem.pixel(np.array(-89.9), np.array(0.0))
    assert lin < 50 and col == pytest.approx(50)
    lin, col = dem.pixel(np.array(-89.9), np.array(90.0))
    assert col > 50 and lin == pytest.approx(50)


def test_elevacao_exata_na_esfera():
    # Mesmo raio, distância d: o ponto fica d/(2R) rad abaixo do horizonte.
    d = 10_000.0
    assert hz.elevacao_graus(0.0, 0.0, d) == pytest.approx(-np.degrees(d / (2 * hz.R_LUA_M)), rel=1e-6)
    # 1 km acima a 10 km: ~ atan(0,1) menos a curvatura.
    assert hz.elevacao_graus(0.0, 1000.0, d) == pytest.approx(5.54, abs=0.02)


def test_terreno_plano_da_a_depressao_do_horizonte():
    dem = dem_sintetico(np.zeros((1501, 1501)))
    r = hz.calcular_horizonte({"id": "t", "lat": -90.0, "lon": 0.0}, [dem], altura_observador_m=2.0)
    h = np.array(r["horizon_deg"])
    # Depressão do horizonte de uma esfera vista de 2 m: −sqrt(2h/R).
    esperado = -np.degrees(np.sqrt(2 * 2.0 / hz.R_LUA_M))
    assert np.allclose(h, esperado, atol=0.003)
    assert r["mock"] is False and validar_horizonte(r) == []


@pytest.mark.parametrize("deslocamento, az_esperado", [
    ((0, +125), 90),    # coluna maior = leste
    ((-125, 0), 0),     # linha menor = mais longe do polo = norte
    ((0, -125), 270),   # oeste
    ((+125, 0), 180),   # sul (na direção do polo)
])
def test_montanha_aparece_no_azimute_certo(deslocamento, az_esperado):
    """Confere a convenção 0 = Norte, sentido horário, com geometria independente."""
    n = 2001
    alt = np.zeros((n, n))
    dem = dem_sintetico(alt)
    # Local a 30 km do polo, em lon 0: fica acima do centro da imagem.
    lat = -90 + np.degrees(30_000 / hz.R_LUA_M)
    lin, col = (int(round(v)) for v in dem.pixel(np.array(lat), np.array(0.0)))
    dl, dc = deslocamento
    alt[lin + dl - 3: lin + dl + 4, col + dc - 3: col + dc + 4] = 1000.0
    dem = dem_sintetico(alt)
    r = hz.calcular_horizonte({"id": "t", "lat": lat, "lon": 0.0}, [dem])
    h = np.array(r["horizon_deg"])
    assert int(np.argmax(h)) == az_esperado
    assert h.max() == pytest.approx(5.5, abs=0.3)  # 1 km a ~10 km


def test_local_fora_da_cobertura():
    dem = dem_sintetico(np.zeros((101, 101)))
    with pytest.raises(ValueError, match="fora da cobertura"):
        hz.calcular_horizonte({"id": "apollo11", "lat": 0.674, "lon": 23.473}, [dem])


# ---------------------------------------------------------------- LOLA real

@pytest.fixture(scope="module")
def dems():
    try:
        return hz.carregar_dems(baixar=False)
    except FileNotFoundError as e:
        pytest.skip(f"DEMs do LOLA ausentes: {e}")


# Centros de crateras conhecidas (graus; aproximados). Só a orientação
# correta da projeção põe todos eles numa depressão.
CRATERAS = [("shackleton", -89.67, 129.78, 10), ("haworth", -87.45, -4.14, 25),
            ("nobile", -85.29, 53.54, 36), ("cabeus", -85.33, -42.13, 49),
            ("de_gerlache", -88.5, -87.1, 16), ("faustini", -87.3, 77.0, 20)]


@pytest.mark.parametrize("nome, lat, lon, raio_km", CRATERAS, ids=[c[0] for c in CRATERAS])
def test_crateras_sao_depressoes(dems, nome, lat, lon, raio_km):
    centro = hz._altura(dems, np.array([lat]), np.array([lon]))[0]
    az = np.arange(0, 360, 10.0)
    la, lo = hz._destino(lat, lon, az, np.array([raio_km * 1000.0]))
    borda = np.nanmean(hz._altura(dems, la, lo))
    assert centro < borda - 800, f"{nome}: centro {centro:.0f} m, borda {borda:.0f} m"


def test_dems_concordam(dems):
    rng = np.random.default_rng(0)
    lat, lon = rng.uniform(-89.5, -81, 2000), rng.uniform(-180, 180, 2000)
    dif = np.abs(dems[0].altura(lat, lon) - dems[1].altura(lat, lon))
    assert np.median(dif) < 5 and np.percentile(dif, 95) < 20


def test_rotulo_conferido(dems):
    assert [d.nome for d in dems] == ["LDEM_80S_80M", "LDEM_75S_240M"]
    assert [d.m_por_pixel for d in dems] == [80.0, 240.0]


@pytest.mark.parametrize("site", POLARES)
def test_arquivos_reais_no_contrato(site):
    caminho = RAIZ / "data" / "horizon" / f"{site}.json"
    h = json.loads(caminho.read_text(encoding="utf-8"))
    if h.get("mock"):
        pytest.skip("data/horizon ainda é mock")
    assert validar_horizonte(h) == []
    assert h["meta"]["alcance_min_m"] >= 250_000  # relevo distante coberto


def test_fundo_da_haworth_e_sombra_permanente(dems):
    """O centro da cratera Haworth nunca vê o Sol (que não passa de ~1,6°)."""
    h = hz.calcular_horizonte({"id": "haworth_centro", "lat": -87.45, "lon": -4.14}, dems)
    assert min(h["horizon_deg"]) > 1.7


def test_topo_do_malapert_ve_tudo_abaixo(dems):
    """No pixel mais alto do maciço o horizonte fica abaixo de 0° em todo azimute."""
    h = hz.calcular_horizonte({"id": "topo", "lat": -85.9876, "lon": 2.0528}, dems)
    assert max(h["horizon_deg"]) < 0
    assert h["meta"]["altura_local_m"] == pytest.approx(5172, abs=1)
