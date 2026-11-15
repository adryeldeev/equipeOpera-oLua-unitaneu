"""Testes de pipeline/metrics.py. Sem rede e sem kernels.

    python -m pytest pipeline/tests/test_metrics.py -v
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from pipeline import metrics as m
from pipeline.export import validar_metricas

RAIZ = Path(__file__).resolve().parents[2]
SITES = ["shackleton", "malapert", "nobile", "haworth", "apollo11"]
UTC = timezone.utc


# ---------------------------------------------------------------- auxiliares

def ceu_sint(el_sol, el_terra=None, az_sol=None, az_terra=None, rad_sol=0.27,
             rad_terra=0.95, step_min=60, mock=False, site="teste"):
    """Céu sintético com o mesmo formato do contrato."""
    el_sol = np.asarray(el_sol, dtype=float)
    n = el_sol.size
    el_terra = np.full(n, 10.0) if el_terra is None else np.asarray(el_terra, dtype=float)

    def corpo(az, el, rad):
        az = np.zeros(n) if az is None else np.broadcast_to(np.asarray(az, dtype=float), (n,))
        return {"az": az.tolist(), "el": el.tolist(), "rad_deg": [rad] * n}

    return {"site": site, "frame": "MOON_ME", "start": "2027-01-01T00:00:00Z",
            "step_min": step_min, "sun": corpo(az_sol, el_sol, rad_sol),
            "earth": corpo(az_terra, el_terra, rad_terra), "mock": mock}


def horiz(valor=0.0, site="teste", mock=False):
    h = valor if isinstance(valor, list) else [float(valor)] * 360
    return {"site": site, "az_step_deg": 1, "horizon_deg": h, "mock": mock}


def doze_por_dia(dias=3):
    """Sol visível nas 12 primeiras horas de cada dia (passo de 1 h)."""
    return np.tile(np.r_[np.full(12, 5.0), np.full(12, -5.0)], dias)


def carregar(pasta, tipo, site):
    with open(RAIZ / pasta / tipo / f"{site}.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def reais():
    """Céu real (data/sky) + horizonte mock (data_mock/horizon), por local."""
    return {s: (carregar("data", "sky", s), carregar("data_mock", "horizon", s)) for s in SITES}


# 1. Casos extremos ----------------------------------------------------------

def test_horizonte_plano_sol_sempre_acima():
    r = m.calcular_metricas(ceu_sint(np.full(72, 1.0)), horiz(0.0), 0, 72, 0.5, 0.2)
    assert r["energy"]["pct"] == 1.0
    assert r["energy"]["longest_with_h"] == 72
    assert r["energy"]["longest_without_h"] == 0


def test_horizonte_alto_nada_visivel():
    r = m.calcular_metricas(ceu_sint(np.full(72, 1.0), np.full(72, 1.0)), horiz(30.0), 0, 72, 0.5, 0.2)
    assert r["energy"]["pct"] == 0.0 and r["comms"]["pct"] == 0.0
    assert r["energy"]["longest_without_h"] == 72
    assert r["class"] == "critico"


@pytest.mark.parametrize("site", SITES)
def test_horizonte_alto_com_ceu_real(reais, site):
    ceu, _ = reais[site]
    acima = max(max(ceu["sun"]["el"]), max(ceu["earth"]["el"])) + 2
    r = m.calcular_metricas(ceu, horiz(acima, site), 0, 720, 0.5, 0.2)
    assert r["energy"]["pct"] == 0.0 and r["comms"]["pct"] == 0.0


# 2. Caso sintético com visibilidade conhecida -------------------------------

def test_doze_horas_por_dia():
    r = m.calcular_metricas(ceu_sint(doze_por_dia(3)), horiz(0.0), 0, 72, 0.5, 0.2)
    e = r["energy"]
    assert e["pct"] == 0.5
    assert e["longest_with_h"] == 12 and e["longest_without_h"] == 12
    assert e["daily"] == [{"date": "2027-01-01T00:00:00Z", "pct": 0.5},
                          {"date": "2027-01-02T00:00:00Z", "pct": 0.5},
                          {"date": "2027-01-03T00:00:00Z", "pct": 0.5}]
    assert r["comms"]["pct"] == 1.0 and r["comms"]["longest_without_h"] == 0
    assert r["both"] == {"pct": 0.5, "longest_h": 12}
    assert r["score"] == 0.5 and r["class"] == "ideal"
    assert r["window"] == {"start": "2027-01-01T00:00:00Z", "hours": 72}


def test_janela_deslocada_e_dia_parcial():
    ceu = ceu_sint(doze_por_dia(3))
    r = m.calcular_metricas(ceu, horiz(0.0), 6, 48, 0.5, 0.2)
    assert r["window"]["start"] == "2027-01-01T06:00:00Z"
    assert r["energy"]["pct"] == 0.5
    assert r["energy"]["longest_with_h"] == 12 and r["energy"]["longest_without_h"] == 12
    assert [d["date"] for d in r["energy"]["daily"]] == ["2027-01-01T06:00:00Z", "2027-01-02T06:00:00Z"]

    # 30 h: um dia cheio (0,5) e um bloco de 6 h só com Sol abaixo.
    r = m.calcular_metricas(ceu, horiz(0.0), 12, 30, 0.5, 0.2)
    assert [d["pct"] for d in r["energy"]["daily"]] == [0.5, 0.0]


def test_passo_de_30_min():
    el = np.repeat(doze_por_dia(2), 2)  # mesmo padrão, passo de 30 min
    r = m.calcular_metricas(ceu_sint(el, step_min=30), horiz(0.0), 0, 48, 0.5, 0.2)
    assert r["energy"]["pct"] == 0.5 and r["energy"]["longest_with_h"] == 12
    assert len(r["energy"]["daily"]) == 2


# 3. Fronteira da regra do disco ----------------------------------------------

def test_disco_cruzando_o_horizonte_conta_como_visivel():
    # Horizonte em 2°, raio 0,27°: centro em 1,9° -> topo em 2,17° (visível).
    v = m.visibilidade(ceu_sint([1.9, 1.7, 1.73]), horiz(2.0))
    # 1,7 + 0,27 = 1,97 (abaixo); 1,73 + 0,27 = 2,0 (só encosta: não visível).
    assert v["sol_visivel"].tolist() == [True, False, False]


def test_margem_desloca_a_fronteira():
    ceu = ceu_sint([1.9])
    assert m.visibilidade(ceu, horiz(2.0), margem_graus=0.1)["sol_visivel"].tolist() == [True]
    assert m.visibilidade(ceu, horiz(2.0), margem_graus=0.2)["sol_visivel"].tolist() == [False]


def test_horizonte_interpolado_com_wrap():
    h = [0.0] * 360
    h[11] = 10.0   # entre 10° e 11°: rampa de 0 a 10
    h[0] = 10.0    # entre 359° e 360°=0°: rampa de 0 a 10
    az = [10.5, 10.0, 11.0, 359.5, 0.0, 360.0, -0.5]
    assert m.horizonte_em(horiz(h), az).tolist() == [5.0, 0.0, 10.0, 5.0, 10.0, 10.0, 5.0]


def test_horizonte_com_passo_diferente_de_1():
    h = {"site": "teste", "az_step_deg": 2, "horizon_deg": list(np.arange(180.0))}
    assert m.horizonte_em(h, [3.0, 359.0]).tolist() == [1.5, 89.5]
    with pytest.raises(ValueError, match="não cobrem 360"):
        m.horizonte_em({"az_step_deg": 1, "horizon_deg": [0.0] * 359}, [0.0])


# 4. Classes ------------------------------------------------------------------

@pytest.mark.parametrize("score, classe", [(0.19, "critico"), (0.2, "moderado"),
                                           (0.49, "moderado"), (0.5, "ideal")])
def test_classes(score, classe):
    assert m.classificar(score, ok=0.5, crit=0.2) == classe


@pytest.mark.parametrize("ok, crit", [(0.2, 0.5), (0.5, 0.5), (50, 20), (0.5, -0.1)])
def test_limiares_invalidos(ok, crit):
    with pytest.raises(ValueError):
        m.calcular_metricas(ceu_sint(np.ones(24)), horiz(), 0, 24, ok, crit)


def test_crit_maior_que_ok_mensagem_em_portugues():
    with pytest.raises(ValueError, match="deve ser menor que o limiar ok"):
        m.classificar(0.3, ok=0.2, crit=0.5)


# 5. Incerteza ----------------------------------------------------------------

@pytest.mark.parametrize("site", SITES)
def test_incerteza_envolve_o_score(reais, site):
    ceu, hz = reais[site]
    r = m.calcular_metricas(ceu, hz, 0, 720, 0.5, 0.2)
    inc = r["incerteza"]
    assert inc["margem_graus"] == 1.0
    assert inc["score_min"] <= r["score"] <= inc["score_max"]


def test_incerteza_zero_coincide_com_score(reais):
    ceu, hz = reais["malapert"]
    r = m.calcular_metricas(ceu, hz, 0, 720, 0.5, 0.2, incerteza_graus=0.0)
    assert r["incerteza"]["score_min"] == r["score"] == r["incerteza"]["score_max"]


def test_incerteza_sintetica():
    # Sol sempre a 0,5° (topo em 0,77°), Terra alta. Horizonte em 0:
    # com +1° some (score 0); com −1° continua visível (score 1).
    r = m.calcular_metricas(ceu_sint(np.full(24, 0.5)), horiz(0.0), 0, 24, 0.5, 0.2)
    assert (r["incerteza"]["score_min"], r["score"], r["incerteza"]["score_max"]) == (0.0, 1.0, 1.0)


# 6. Série por atraso ---------------------------------------------------------

@pytest.mark.parametrize("site", SITES)
def test_serie_por_atraso_bate_com_calcular_metricas(reais, site):
    ceu, hz = reais[site]
    i0 = 100
    passos_dia = 1440 // ceu["step_min"]
    serie = m.serie_por_atraso(ceu, hz, i0, 720, range(15), 0.5, 0.2)
    assert len(serie) == 15
    assert [p["atraso_dias"] for p in serie] == list(range(15))
    for p in serie:
        r = m.calcular_metricas(ceu, hz, i0 + p["atraso_dias"] * passos_dia, 720, 0.5, 0.2)
        assert p["score"] == r["score"]
        assert p["class"] == r["class"]


def test_serie_por_atraso_fora_do_alcance(reais):
    ceu, hz = reais["malapert"]
    ultimo = len(ceu["sun"]["el"]) - 720
    with pytest.raises(ValueError, match="fora do alcance"):
        m.serie_por_atraso(ceu, hz, ultimo, 720, range(15), 0.5, 0.2)


# Outras regras ---------------------------------------------------------------

def test_mock_propagado():
    el = np.ones(24)
    assert m.calcular_metricas(ceu_sint(el), horiz(), 0, 24)["mock"] is False
    assert m.calcular_metricas(ceu_sint(el, mock=True), horiz(), 0, 24)["mock"] is True
    assert m.calcular_metricas(ceu_sint(el), horiz(mock=True), 0, 24)["mock"] is True
    sem_chave = horiz()
    del sem_chave["mock"]
    assert m.calcular_metricas(ceu_sint(el), sem_chave, 0, 24)["mock"] is False


@pytest.mark.parametrize("inicio, horas", [(-1, 24), (0, 25), (10, 24), (0, 0), (0, 1.5)])
def test_janela_invalida(inicio, horas):
    with pytest.raises(ValueError):
        m.calcular_metricas(ceu_sint(np.ones(24)), horiz(), inicio, horas)


def test_mensagem_janela_fora_do_alcance():
    with pytest.raises(ValueError, match=r"cobre 2027-01-01T00:00:00Z a 2027-01-02T00:00:00Z"):
        m.calcular_metricas(ceu_sint(np.ones(24)), horiz(), 10, 24)


def test_locais_diferentes():
    with pytest.raises(ValueError, match="locais diferentes"):
        m.visibilidade(ceu_sint([1.0]), horiz(site="outro"))


def test_indice_de():
    ceu = ceu_sint(np.ones(48))
    assert m.indice_de(ceu, datetime(2027, 1, 2, 3, tzinfo=UTC)) == 27
    with pytest.raises(ValueError, match="grade"):
        m.indice_de(ceu, datetime(2027, 1, 1, 0, 30, tzinfo=UTC))
    with pytest.raises(ValueError, match="fora do alcance"):
        m.indice_de(ceu, datetime(2027, 1, 3, tzinfo=UTC))


# 8. Integração: data/sky real + data_mock/horizon ----------------------------

@pytest.mark.parametrize("site", SITES)
def test_integracao_passa_no_schema(reais, site):
    ceu, hz = reais[site]
    r = m.calcular_metricas(ceu, hz, 0, m.JANELA_H_PADRAO, m.OK_PADRAO, m.CRIT_PADRAO)
    assert validar_metricas(r) == []
    json.dumps(r, allow_nan=False)  # serializável como a API vai devolver
    assert r["site"] == site
    assert r["mock"] is True        # o horizonte ainda é mock
    assert len(r["energy"]["daily"]) == m.JANELA_H_PADRAO // 24


def test_schema_rejeita_saida_incoerente(reais):
    ceu, hz = reais["malapert"]
    r = m.calcular_metricas(ceu, hz, 0, 720, 0.5, 0.2)
    r["energy"]["pct"] = 50
    r["class"] = "verde"
    r["incerteza"]["score_min"] = 1.0
    erros = validar_metricas(r)
    assert any("energy.pct" in e for e in erros)
    assert any(e.startswith("class") for e in erros)
    assert any(e.startswith("incerteza") for e in erros)
