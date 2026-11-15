"""API da ferramenta de pouso no polo sul lunar (FastAPI).

Rodar na raiz do repositório:

    uvicorn api.main:app --port 8001 --reload
    # documentação interativa: http://localhost:8001/docs

Endpoints (todos GET, JSON):
    /api/saude                       estado da API e das efemérides
    /api/sites                       lista de locais (data/sites.json)
    /api/sites/{id}                  um local
    /api/sites/{id}/horizonte        horizonte do relevo (data/horizon/<id>.json)
    /api/sites/{id}/ceu              Sol e Terra no período pedido
    /api/sites/{id}/metricas         métricas de energia e comunicação numa janela
    /api/sites/{id}/atrasos          score por atraso do pouso (0..N dias)

Céu: calculado na hora com pipeline.ephemeris (Skyfield, kernels em
cache/). PLANO B: se os kernels não carregarem, usa data/sky/<id>.json
(2027, passo de 60 min) e avisa em "fonte.ceu".

Limiares ok/crit: frações (0–1). Se vierem em porcentagem (algum > 1),
os dois são divididos por 100.

Variáveis de ambiente:
    DADOS_DIR        pasta com sites.json, horizon/ e sky/ (padrão: data/)
    CORS_ORIGENS     origens do front, separadas por vírgula
    BAIXAR_KERNELS   "0" para não baixar kernels no startup (força o plano B se faltarem)
"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from pipeline import ephemeris as ef
from pipeline import metrics as mt

RAIZ = Path(__file__).resolve().parents[1]
VERSAO = "1.0.0"

CORS_PADRAO = ("http://localhost:8000,http://127.0.0.1:8000,"
               "http://localhost:8080,http://127.0.0.1:8080")
ATRASO_MAX_DIAS = 30
JANELA_MAX_H = 24 * 366

# Estado preenchido no startup.
estado: dict = {"efemerides": False, "erro_efemerides": None}


def _dados_dir() -> Path:
    return Path(os.environ.get("DADOS_DIR", RAIZ / "data"))


# ---------------------------------------------------------------- startup

@asynccontextmanager
async def _ciclo(app: FastAPI):
    baixar = os.environ.get("BAIXAR_KERNELS", "1") != "0"
    try:
        ef.carregar_recursos(baixar=baixar)
        estado.update(efemerides=True, erro_efemerides=None)
    except Exception as e:  # sem kernels/rede: segue no plano B (data/sky)
        estado.update(efemerides=False, erro_efemerides=f"{type(e).__name__}: {e}")
    yield


app = FastAPI(
    title="LanderBnB: Lunar South Pole Landing Planner",
    version=VERSAO,
    description=("Sun (power) and Earth (direct-to-Earth communication) above the real terrain, "
                 "per landing site and landing date. Sky: Skyfield + JPL DE440; terrain: LRO LOLA."),
    lifespan=_ciclo,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.environ.get("CORS_ORIGENS", CORS_PADRAO).split(",") if o.strip()],
    allow_methods=["GET"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------- leitura de data/

@lru_cache(maxsize=64)
def _ler_cache(caminho: str, mtime_ns: int):
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)


def _ler(caminho: Path):
    """JSON de data/, com cache em memória invalidado quando o arquivo muda."""
    try:
        return _ler_cache(str(caminho), caminho.stat().st_mtime_ns)
    except FileNotFoundError:
        raise HTTPException(503, f"missing data file: {caminho.name} "
                                 "(run python -m pipeline.export --out data)")


def _sites() -> dict[str, dict]:
    return {s["id"]: s for s in _ler(_dados_dir() / "sites.json")}


def _site(site_id: str) -> dict:
    sites = _sites()
    if site_id not in sites:
        raise HTTPException(404, f"site '{site_id}' does not exist; available: {', '.join(sites)}")
    return sites[site_id]


def _horizonte(site_id: str) -> dict:
    return _ler(_dados_dir() / "horizon" / f"{site_id}.json")


# ---------------------------------------------------------------- céu

def _utc(d: datetime) -> datetime:
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)


def _ceu(site: dict, inicio: datetime, horas: float, passo_min: int) -> tuple[dict, int, str]:
    """(céu, índice do início, fonte). Skyfield; se indisponível, data/sky."""
    inicio = _utc(inicio)
    if estado["efemerides"]:
        try:
            return ef.gerar_ceu(site, inicio, horas / 24, passo_min), 0, "skyfield"
        except ef.ForaDoIntervalo as e:
            raise HTTPException(
                422, f"date out of the supported range "
                     f"({e.inicio_suportado:%Y-%m-%d} to {e.fim_suportado:%Y-%m-%d} UTC)") from e
        except ef.ParametroInvalido as e:
            raise HTTPException(422, f"invalid ephemeris parameter: {e}") from e

    ceu = _ler(_dados_dir() / "sky" / f"{site['id']}.json")
    fonte = f"data/sky (fallback: {estado['erro_efemerides']})"
    if passo_min != ceu["step_min"]:
        raise HTTPException(422, f"in fallback mode (data/sky) only a {ceu['step_min']}-min step is available")
    try:
        i0 = mt.indice_de(ceu, inicio)
    except ValueError as e:
        raise HTTPException(422, f"fallback mode (data/sky, year 2027 only): {e}") from e
    return ceu, i0, fonte


def _limiares(ok: float, crit: float) -> tuple[float, float]:
    if ok > 1 or crit > 1:  # vieram em porcentagem
        ok, crit = ok / 100, crit / 100
    return ok, crit


def _fonte(fonte_ceu: str, hz: dict) -> dict:
    return {"ceu": fonte_ceu,
            "horizonte": "mock" if hz.get("mock") else hz.get("meta", {}).get("fonte", "real")}


# ---------------------------------------------------------------- endpoints

Inicio = Query(..., description="window start (landing time), ISO 8601; no timezone = UTC",
               examples=["2027-03-01T00:00:00Z"])
Passo = Query(60, ge=1, le=1440, description="sky time step in minutes")
Janela = Query(mt.JANELA_H_PADRAO, gt=0, le=JANELA_MAX_H, description="window length in hours")
Ok = Query(mt.OK_PADRAO, ge=0, le=100, description="ideal threshold (fraction 0–1 or %)")
Crit = Query(mt.CRIT_PADRAO, ge=0, le=100, description="critical threshold (fraction 0–1 or %)")


@app.get("/api/saude")
def saude():
    intervalo = None
    if estado["efemerides"]:
        ini, fim = ef.intervalo_suportado()
        intervalo = {"inicio": ini.strftime("%Y-%m-%dT%H:%M:%SZ"), "fim": fim.strftime("%Y-%m-%dT%H:%M:%SZ")}
    return {"status": "ok", "versao": VERSAO, "efemerides": estado["efemerides"],
            "erro_efemerides": estado["erro_efemerides"], "intervalo_suportado": intervalo,
            "padroes": {"janela_h": mt.JANELA_H_PADRAO, "ok": mt.OK_PADRAO, "crit": mt.CRIT_PADRAO,
                        "incerteza_graus": mt.INCERTEZA_PADRAO_GRAUS}}


@app.get("/api/sites")
def listar_sites():
    return list(_sites().values())


@app.get("/api/sites/{site_id}")
def obter_site(site_id: str):
    return _site(site_id)


@app.get("/api/sites/{site_id}/horizonte")
def obter_horizonte(site_id: str):
    _site(site_id)
    return _horizonte(site_id)


@app.get("/api/sites/{site_id}/ceu")
def obter_ceu(site_id: str, inicio: datetime = Inicio,
              dias: float = Query(30, gt=0, le=366), passo_min: int = Passo):
    site = _site(site_id)
    ceu, i0, fonte = _ceu(site, inicio, dias * 24, passo_min)
    return {**_recorte(ceu, i0, dias, passo_min, inicio, fonte), "fonte": fonte}


def _recorte(ceu, i0, dias, passo_min, inicio, fonte):
    """No plano B, recorta o período pedido do arquivo de 1 ano."""
    if fonte == "skyfield":
        return ceu
    n = -(-int(round(dias * 1440)) // passo_min)
    if i0 + n > len(ceu["sun"]["el"]):
        raise HTTPException(422, "fallback mode (data/sky, year 2027 only): period out of the file")
    corte = slice(i0, i0 + n)
    return {**ceu, "start": _utc(inicio).strftime("%Y-%m-%dT%H:%M:%SZ"),
            **{c: {k: v[corte] for k, v in ceu[c].items()} for c in ("sun", "earth")}}


@app.get("/api/sites/{site_id}/visibilidade")
def obter_visibilidade(site_id: str, inicio: datetime = Inicio,
                       dias: float = Query(30, gt=0, le=60), passo_min: int = Passo,
                       margem_graus: float = Query(0.0, ge=-5, le=5)):
    """Per-sample timeline: position, terrain horizon at that azimuth and whether it is visible.

    Lets the front end draw the sky and simulate the battery without
    re-implementing the visibility rule (it lives only in the pipeline).
    """
    site = _site(site_id)
    hz = _horizonte(site_id)
    ceu, i0, fonte = _ceu(site, inicio, dias * 24, passo_min)
    ceu = _recorte(ceu, i0, dias, passo_min, inicio, fonte)
    v = mt.visibilidade(ceu, hz, margem_graus)
    saida = {"site": site_id, "start": ceu["start"], "step_min": ceu["step_min"],
             "mock": bool(ceu.get("mock")) or bool(hz.get("mock")), "fonte": _fonte(fonte, hz),
             "regra": "visible if el + rad_deg > horizon(az) + margem_graus"}
    for corpo, nome, chave in (("sun", "sol", "sol_visivel"), ("earth", "terra", "terra_visivel")):
        c = ceu[corpo]
        saida[nome] = {
            "az": c["az"], "el": c["el"], "rad_deg": c["rad_deg"],
            "horizonte": [round(float(x), 3) for x in mt.horizonte_em(hz, c["az"])],
            "visivel": v[chave].tolist(),
        }
    return saida


@app.get("/api/sites/{site_id}/metricas")
def obter_metricas(site_id: str, inicio: datetime = Inicio, janela_h: float = Janela,
                   passo_min: int = Passo, ok: float = Ok, crit: float = Crit,
                   margem_graus: float = Query(0.0, ge=-5, le=5),
                   incerteza_graus: float = Query(mt.INCERTEZA_PADRAO_GRAUS, ge=0, le=5)):
    site = _site(site_id)
    hz = _horizonte(site_id)
    ok, crit = _limiares(ok, crit)
    ceu, i0, fonte = _ceu(site, inicio, janela_h, passo_min)
    try:
        m = mt.calcular_metricas(ceu, hz, i0, janela_h, ok, crit,
                                 margem_graus=margem_graus, incerteza_graus=incerteza_graus)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return {**m, "fonte": _fonte(fonte, hz)}


@app.get("/api/sites/{site_id}/atrasos")
def obter_atrasos(site_id: str, inicio: datetime = Inicio, janela_h: float = Janela,
                  atraso_max_dias: int = Query(14, ge=0, le=ATRASO_MAX_DIAS),
                  passo_min: int = Passo, ok: float = Ok, crit: float = Crit,
                  margem_graus: float = Query(0.0, ge=-5, le=5)):
    site = _site(site_id)
    hz = _horizonte(site_id)
    ok, crit = _limiares(ok, crit)
    # Um único céu cobrindo a janela do maior atraso.
    ceu, i0, fonte = _ceu(site, inicio, janela_h + atraso_max_dias * 24, passo_min)
    try:
        serie = mt.serie_por_atraso(ceu, hz, i0, janela_h, range(atraso_max_dias + 1),
                                    ok, crit, margem_graus=margem_graus)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return {
        "site": site_id,
        "inicio": _utc(inicio).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "janela_h": janela_h,
        "thresholds": {"ok": ok, "crit": crit},
        "mock": bool(ceu.get("mock")) or bool(hz.get("mock")),
        "fonte": _fonte(fonte, hz),
        "serie": serie,
    }


# ---------------------------------------------------------------- front e dados estáticos
# Um comando só sobe tudo: http://localhost:8001/ abre o front (web/) e
# /data/ serve os JSON do contrato (plano B do front). Como a página e a
# API ficam na mesma origem, não depende de CORS.

from fastapi.responses import RedirectResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402


@app.get("/", include_in_schema=False)
def raiz():
    return RedirectResponse("/web/")


if (RAIZ / "web").is_dir():
    app.mount("/web", StaticFiles(directory=RAIZ / "web", html=True), name="web")
if _dados_dir().is_dir():
    app.mount("/data", StaticFiles(directory=_dados_dir()), name="data")
