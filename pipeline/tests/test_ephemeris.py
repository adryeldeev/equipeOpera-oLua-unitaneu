"""Testes de pipeline/ephemeris.py. Nenhum teste usa rede.

Rodar na raiz do repositório:
    python -m pytest pipeline/tests -v

Se os kernels não estiverem em cache/, os testes são pulados (rode a CLI
uma vez para baixá-los).
"""

import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
import yaml

from pipeline import ephemeris as ef

RAIZ = Path(__file__).resolve().parents[2]
UTC = timezone.utc
INICIO = datetime(2027, 1, 1, tzinfo=UTC)

try:
    ef.carregar_recursos(baixar=False)
except FileNotFoundError as e:
    pytest.skip(f"kernels ausentes, testes pulados: {e}", allow_module_level=True)


def _sites():
    with open(RAIZ / "pipeline" / "config" / "sites.yaml", encoding="utf-8") as f:
        return {s["id"]: s for s in yaml.safe_load(f)["sites"]}


SITES = _sites()
POLARES = [s for s in SITES.values() if s["lat"] < -85]


@pytest.fixture(scope="module")
def ano():
    """1 ano em passo de 2 h por local: cobre o ciclo da declinação do Sol."""
    return {i: ef.gerar_ceu(s, INICIO, 365, 120) for i, s in SITES.items()}


# 1. Sol rasante no polo -----------------------------------------------------
# A elevação máxima do Sol é ~ (90 - |lat|) + 1,54° (inclinação do equador
# lunar em relação à eclíptica). O limite fixo de 1,7° só vale para quem
# está quase no polo (Shackleton); para os outros usamos a fórmula.

@pytest.mark.parametrize("site", POLARES, ids=lambda s: s["id"])
def test_sol_rasante_no_polo(ano, site):
    el = np.array(ano[site["id"]]["sun"]["el"])
    limite = (90 - abs(site["lat"])) + 1.6
    assert np.abs(el).max() <= limite


def test_quase_no_polo_abaixo_de_1_7_graus():
    # Ponto fixo a 0,1° do polo (o local "shackleton" do YAML agora fica na
    # borda, a 0,23° do polo, onde o limite é a fórmula do teste acima).
    ceu = ef.gerar_ceu({"id": "polo", "lat": -89.9, "lon": 0.0}, INICIO, 365, 120)
    assert np.abs(ceu["sun"]["el"]).max() <= 1.7


# 2. Raio angular ------------------------------------------------------------
# Terra: 0,89° no apogeu (~406.700 km) a ~1,03° no perigeu.

@pytest.mark.parametrize("sid", list(SITES))
def test_raio_angular(ano, sid):
    sol = np.array(ano[sid]["sun"]["rad_deg"])
    terra = np.array(ano[sid]["earth"]["rad_deg"])
    assert 0.25 <= sol.min() and sol.max() <= 0.28
    assert 0.89 <= terra.min() and terra.max() <= 1.05


# 3. Forma -------------------------------------------------------------------

@pytest.mark.parametrize("sid", list(SITES))
def test_forma(ano, sid):
    c = ano[sid]
    assert list(c) == ["site", "frame", "start", "step_min", "sun", "earth", "mock"]
    assert c["site"] == sid and c["frame"] == "MOON_ME" and c["mock"] is False
    assert c["start"] == "2027-01-01T00:00:00Z" and c["step_min"] == 120
    n = 365 * 12
    for corpo in ("sun", "earth"):
        assert set(c[corpo]) == {"az", "el", "rad_deg"}
        az, el, rad = (np.array(c[corpo][k]) for k in ("az", "el", "rad_deg"))
        assert len(az) == len(el) == len(rad) == n
        assert not np.isnan(np.concatenate([az, el, rad])).any()
        assert (az >= 0).all() and (az < 360).all()
        assert (el >= -90).all() and (el <= 90).all()


def test_tamanho_30_dias_passo_60():
    c = ef.gerar_ceu(SITES["nobile"], INICIO, 30, 60)
    assert len(c["sun"]["az"]) == 720


# 4. Apollo 11 (perto do centro da face visível) -----------------------------

def test_apollo11(ano):
    c = ano["apollo11"]
    assert max(c["sun"]["el"]) > 80
    assert min(c["earth"]["el"]) > 0


# 5. Reprodutibilidade -------------------------------------------------------

def test_reprodutivel():
    a = ef.gerar_ceu(SITES["malapert"], INICIO, 10, 30)
    b = ef.gerar_ceu(SITES["malapert"], INICIO, 10, 30)
    assert a == b


# 6. Erros -------------------------------------------------------------------

@pytest.mark.parametrize("dias", [0, -1, float("nan"), "30"])
def test_dias_invalido(dias):
    with pytest.raises(ef.ParametroInvalido):
        ef.gerar_ceu(SITES["haworth"], INICIO, dias, 60)


@pytest.mark.parametrize("passo", [0, 1441, -5, 1.5, True])
def test_passo_invalido(passo):
    with pytest.raises(ef.ParametroInvalido):
        ef.gerar_ceu(SITES["haworth"], INICIO, 1, passo)


def test_instantes_demais():
    with pytest.raises(ef.ParametroInvalido):
        ef.gerar_ceu(SITES["haworth"], INICIO, 100, 1)  # 144.000 instantes


def test_inicio_sem_fuso():
    with pytest.raises(ef.ParametroInvalido):
        ef.gerar_ceu(SITES["haworth"], datetime(2027, 1, 1), 1, 60)


def test_site_invalido():
    with pytest.raises(ef.ParametroInvalido):
        ef.gerar_ceu({"id": "x", "lat": -95, "lon": 0}, INICIO, 1, 60)


@pytest.mark.parametrize("inicio", [datetime(1800, 1, 1, tzinfo=UTC),
                                    datetime(2150, 1, 19, tzinfo=UTC),
                                    datetime(2300, 1, 1, tzinfo=UTC)])
def test_fora_do_intervalo(inicio):
    with pytest.raises(ef.ForaDoIntervalo) as e:
        ef.gerar_ceu(SITES["haworth"], inicio, 5, 60)
    ini, fim = ef.intervalo_suportado()
    assert e.value.inicio_suportado == ini and e.value.fim_suportado == fim
    assert f"{ini:%Y-%m-%d}" in str(e.value)


def test_intervalo_suportado():
    ini, fim = ef.intervalo_suportado()
    assert ini.tzinfo is not None and fim.tzinfo is not None
    assert ini.year == 1849 and fim.year == 2150


# Física: altaz() do Skyfield na Lua == rotação manual para leste-norte-cima

def test_altaz_igual_rotacao_manual():
    rec = ef.carregar_recursos()
    lat, lon = -86.0, 0.0
    t = rec.ts.utc(2027, 1, 1, np.arange(0, 24 * 28, 24))
    local = rec.lua + rec.pc.build_latlon_degrees(rec.frame, lat, lon)
    ap = local.at(t).observe(rec.sol).apparent()
    el, az, _ = ap.altaz()

    # Vetor local->Sol (ICRF) levado ao frame MOON_ME.
    v = np.einsum("ijn,jn->in", rec.frame.rotation_at(t), ap.position.km)
    f, l = math.radians(lat), math.radians(lon)
    cima = np.array([math.cos(f) * math.cos(l), math.cos(f) * math.sin(l), math.sin(f)])
    leste = np.array([-math.sin(l), math.cos(l), 0.0])
    norte = np.cross(cima, leste)
    e, n, u = leste @ v, norte @ v, cima @ v
    el_m = np.degrees(np.arctan2(u, np.hypot(e, n)))
    az_m = np.degrees(np.arctan2(e, n)) % 360
    assert np.allclose(el.degrees, el_m, atol=1e-6)
    dif_az = (az.degrees - az_m + 180) % 360 - 180
    assert np.abs(dif_az).max() < 1e-6
