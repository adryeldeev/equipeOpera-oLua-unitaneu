"""Testes da API (FastAPI TestClient). Sem rede: BAIXAR_KERNELS=0.

    python -m pytest api/tests -v

Os testes do caminho "skyfield" são pulados se os kernels não estiverem em
cache/; os do plano B (data/sky) rodam sempre.
"""

import json
import os
from pathlib import Path

import pytest

os.environ["BAIXAR_KERNELS"] = "0"

from fastapi.testclient import TestClient  # noqa: E402

from api import main  # noqa: E402
from pipeline import metrics as mt  # noqa: E402
from pipeline.export import validar_ceu, validar_horizonte, validar_metricas  # noqa: E402

RAIZ = Path(__file__).resolve().parents[2]
INICIO = "2027-03-01T00:00:00Z"


@pytest.fixture(scope="module")
def cliente():
    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def com_kernels(cliente):
    if not main.estado["efemerides"]:
        pytest.skip("kernels ausentes em cache/")


@pytest.fixture
def plano_b(cliente, monkeypatch):
    """Simula a queda das efemérides: a API passa a usar data/sky."""
    monkeypatch.setitem(main.estado, "efemerides", False)
    monkeypatch.setitem(main.estado, "erro_efemerides", "teste")


def _ler(rel):
    return json.loads((RAIZ / rel).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- básicos

def test_saude(cliente):
    r = cliente.get("/api/saude").json()
    assert r["status"] == "ok"
    assert r["padroes"] == {"janela_h": 720, "ok": 0.5, "crit": 0.2, "incerteza_graus": 1.0}


def test_sites_igual_ao_contrato(cliente):
    assert cliente.get("/api/sites").json() == _ler("data/sites.json")
    assert cliente.get("/api/sites/malapert").json()["id"] == "malapert"


def test_local_inexistente_404(cliente):
    r = cliente.get("/api/sites/xyz/metricas", params={"inicio": INICIO})
    assert r.status_code == 404
    assert "does not exist" in r.json()["detail"]


def test_horizonte(cliente):
    h = cliente.get("/api/sites/malapert/horizonte").json()
    assert validar_horizonte(h) == []
    assert h == _ler("data/horizon/malapert.json")


def test_cors(cliente):
    r = cliente.get("/api/saude", headers={"Origin": "http://localhost:8000"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:8000"


# ---------------------------------------------------------------- métricas

@pytest.mark.parametrize("site", ["shackleton", "malapert", "nobile", "haworth", "mons_mouton", "apollo11"])
def test_metricas_passa_no_schema(cliente, com_kernels, site):
    r = cliente.get(f"/api/sites/{site}/metricas", params={"inicio": INICIO})
    assert r.status_code == 200, r.text
    m = r.json()
    assert validar_metricas(m) == []
    assert m["window"] == {"start": INICIO, "hours": 720}
    assert m["fonte"]["ceu"] == "skyfield"
    assert m["mock"] is (site == "apollo11")  # só o Apollo 11 tem horizonte mock


def test_metricas_bate_com_o_pipeline(cliente, com_kernels):
    """A API não muda nada: mesmo resultado de chamar o pipeline direto."""
    from datetime import datetime, timezone

    from pipeline import ephemeris as ef
    site = _ler("data/sites.json")[1]
    ceu = ef.gerar_ceu(site, datetime(2027, 3, 1, tzinfo=timezone.utc), 30, 60)
    esperado = mt.calcular_metricas(ceu, _ler(f"data/horizon/{site['id']}.json"), 0, 720, 0.5, 0.2)
    r = cliente.get(f"/api/sites/{site['id']}/metricas", params={"inicio": INICIO}).json()
    r.pop("fonte")
    assert r == esperado


def test_limiares_em_porcentagem(cliente, com_kernels):
    frac = cliente.get("/api/sites/malapert/metricas", params={"inicio": INICIO, "ok": 0.6, "crit": 0.3}).json()
    pct = cliente.get("/api/sites/malapert/metricas", params={"inicio": INICIO, "ok": 60, "crit": 30}).json()
    assert pct["thresholds"] == {"ok": 0.6, "crit": 0.3}
    assert pct["class"] == frac["class"] and pct["score"] == frac["score"]


@pytest.mark.parametrize("params, trecho", [
    ({"inicio": "1700-01-01"}, "out of the supported range"),
    ({"inicio": INICIO, "ok": 0.2, "crit": 0.5}, "must be lower"),
    ({"inicio": INICIO, "janela_h": 1.5}, "not a multiple of the sky time step"),
])
def test_erros_422_com_mensagem_clara(cliente, com_kernels, params, trecho):
    r = cliente.get("/api/sites/malapert/metricas", params=params)
    assert r.status_code == 422
    assert trecho in r.json()["detail"]


def test_parametro_fora_da_faixa_e_422(cliente):
    r = cliente.get("/api/sites/malapert/metricas", params={"inicio": INICIO, "passo_min": 0})
    assert r.status_code == 422


# ---------------------------------------------------------------- atrasos

def test_atrasos(cliente, com_kernels):
    r = cliente.get("/api/sites/malapert/atrasos", params={"inicio": INICIO}).json()
    assert [p["atraso_dias"] for p in r["serie"]] == list(range(15))
    m = cliente.get("/api/sites/malapert/metricas", params={"inicio": INICIO}).json()
    assert r["serie"][0]["score"] == m["score"]
    m3 = cliente.get("/api/sites/malapert/metricas", params={"inicio": "2027-03-04T00:00:00Z"}).json()
    assert r["serie"][3]["score"] == m3["score"]


def test_atraso_max(cliente, com_kernels):
    r = cliente.get("/api/sites/nobile/atrasos", params={"inicio": INICIO, "atraso_max_dias": 3}).json()
    assert len(r["serie"]) == 4


# ---------------------------------------------------------------- céu

def test_ceu(cliente, com_kernels):
    c = cliente.get("/api/sites/haworth/ceu", params={"inicio": INICIO, "dias": 2}).json()
    assert c.pop("fonte") == "skyfield"
    assert validar_ceu(c) == [] and len(c["sun"]["az"]) == 48 and c["start"] == INICIO


# ---------------------------------------------------------------- plano B

def test_plano_b_metricas_iguais(cliente, com_kernels, monkeypatch):
    """data/sky (1 ano gravado) dá as mesmas métricas que o cálculo na hora."""
    normal = cliente.get("/api/sites/shackleton/metricas", params={"inicio": INICIO}).json()
    monkeypatch.setitem(main.estado, "efemerides", False)
    monkeypatch.setitem(main.estado, "erro_efemerides", "teste")
    b = cliente.get("/api/sites/shackleton/metricas", params={"inicio": INICIO}).json()
    assert b["fonte"]["ceu"].startswith("data/sky")
    assert b["score"] == normal["score"] and b["energy"] == normal["energy"]


def test_plano_b_funciona_sem_kernels(cliente, plano_b):
    r = cliente.get("/api/sites/malapert/metricas", params={"inicio": INICIO})
    assert r.status_code == 200 and validar_metricas(r.json()) == []
    a = cliente.get("/api/sites/malapert/atrasos", params={"inicio": INICIO})
    assert a.status_code == 200 and len(a.json()["serie"]) == 15
    c = cliente.get("/api/sites/malapert/ceu", params={"inicio": INICIO, "dias": 1}).json()
    assert len(c["sun"]["az"]) == 24 and c["start"] == INICIO


@pytest.mark.parametrize("params, trecho", [
    ({"inicio": "2030-01-01"}, "out of the sky range"),
    ({"inicio": "2027-03-01T00:30:00Z"}, "grid"),
    ({"inicio": INICIO, "passo_min": 30}, "only a 60-min step"),
])
def test_plano_b_limites(cliente, plano_b, params, trecho):
    r = cliente.get("/api/sites/malapert/metricas", params=params)
    assert r.status_code == 422 and trecho in r.json()["detail"]


# ---------------------------------------------------------------- visibilidade

def test_visibilidade_bate_com_metricas(cliente, com_kernels):
    v = cliente.get("/api/sites/malapert/visibilidade", params={"inicio": INICIO, "dias": 30}).json()
    m = cliente.get("/api/sites/malapert/metricas", params={"inicio": INICIO}).json()
    for nome, chave in (("sol", "energy"), ("terra", "comms")):
        assert len(v[nome]["visivel"]) == 720
        assert sum(v[nome]["visivel"]) / 720 == m[chave]["pct"]
        assert len(v[nome]["horizonte"]) == len(v[nome]["az"]) == 720
    assert v["start"] == INICIO and v["step_min"] == 60 and v["mock"] is False


def test_visibilidade_plano_b(cliente, plano_b):
    v = cliente.get("/api/sites/haworth/visibilidade", params={"inicio": INICIO, "dias": 2}).json()
    assert len(v["sol"]["visivel"]) == 48 and v["fonte"]["ceu"].startswith("data/sky")


def test_serve_front_e_dados(cliente):
    r = cliente.get("/", follow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"] == "/web/"
    assert cliente.get("/data/sites.json").json() == _ler("data/sites.json")
