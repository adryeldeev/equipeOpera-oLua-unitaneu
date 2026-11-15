"""Métricas de energia (Sol visível) e comunicação direta (Terra visível).

Uso como BIBLIOTECA (é o que a API usa):

    from pipeline.metrics import calcular_metricas, serie_por_atraso, indice_de

    i0 = indice_de(ceu, datetime(2027, 3, 1, tzinfo=timezone.utc))
    m = calcular_metricas(ceu, horizonte, i0, janela_h=720, ok=0.5, crit=0.2)
    s = serie_por_atraso(ceu, horizonte, i0, 720, range(15), ok=0.5, crit=0.2)

Funções puras: não leem nem escrevem arquivos e não usam rede.

Entradas (contrato de dados):
    ceu        {site, frame, start, step_min,
                sun:{az[], el[], rad_deg[]}, earth:{az[], el[], rad_deg[]}, mock}
    horizonte  {site, az_step_deg, horizon_deg[360], meta?, mock?}
               horizon_deg[i] = elevação máxima do relevo no azimute
               i * az_step_deg (0 = Norte, sentido horário).

Convenções de saída:
- Frações (pct, score, limiares ok/crit) SEMPRE entre 0 e 1. O front
  formata como %; a API converte se receber 0–100.
- Horas = nº de passos × step_min / 60.
- Datas em ISO 8601 UTC ("2027-01-01T00:00:00Z").
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import numpy as np

# Limiares e janela padrão (frações e horas). A API pode sobrescrever.
OK_PADRAO = 0.5
CRIT_PADRAO = 0.2
# TODO(equipe): confirmar a janela padrão. 720 h = 30 dias, pouco mais de
# um dia solar lunar (29,53 dias): cobre um ciclo completo de luz e sombra.
JANELA_H_PADRAO = 720
# Erro vertical do horizonte derivado do DEM: pode chegar a 1,5–2,5°, e o
# Sol no polo nunca passa de ~1,5° de elevação. Por isso o score vem com
# uma faixa calculada com o horizonte ±INCERTEZA_PADRAO_GRAUS.
INCERTEZA_PADRAO_GRAUS = 1.0

CLASSES = ("ideal", "moderado", "critico")


# ---------------------------------------------------------------- regra

def regra_visivel(el, rad_deg, horizonte_no_az, margem_graus=0.0):
    """REGRA DE VISIBILIDADE (única; troque aqui se a equipe mudar).

    Regra atual: "qualquer parte do disco". O astro é visível se a borda
    superior do disco (centro + raio angular) estiver acima do horizonte
    do relevo naquele azimute, mais a margem:

        el + rad_deg > horizonte(az) + margem_graus

    Alternativa discutida: "fração do disco" (por exemplo, exigir metade
    do disco: el > horizonte + margem). Basta mudar esta função; o resto
    do módulo só consome o array booleano.
    """
    return np.asarray(el) + np.asarray(rad_deg) > np.asarray(horizonte_no_az) + margem_graus


def horizonte_em(horizonte: dict, az) -> np.ndarray:
    """Elevação do relevo nos azimutes `az` (graus), interpolada linearmente.

    Interpola entre os azimutes vizinhos da grade (passo az_step_deg), com
    wrap em 360°: entre o último valor e o primeiro também se interpola.
    """
    h = np.asarray(horizonte["horizon_deg"], dtype=float)
    passo = float(horizonte["az_step_deg"])
    n = h.size
    if n == 0 or passo <= 0 or not math.isclose(n * passo, 360.0):
        raise ValueError(
            f"invalid horizon: {n} values with a {passo}° step do not cover 360°")
    x = np.mod(np.asarray(az, dtype=float), 360.0) / passo
    base = np.floor(x)
    f = x - base
    i0 = base.astype(np.int64) % n
    i1 = (i0 + 1) % n
    return h[i0] * (1.0 - f) + h[i1] * f


# ---------------------------------------------------------------- visibilidade

def _corpo(ceu: dict, nome: str):
    c = ceu[nome]
    return (np.asarray(c["az"], dtype=float), np.asarray(c["el"], dtype=float),
            np.asarray(c["rad_deg"], dtype=float))


def _folgas(ceu: dict, horizonte: dict) -> tuple[np.ndarray, np.ndarray]:
    """(el, rad_deg, horizonte no az) de Sol e Terra, por instante.

    Separada da regra para que a incerteza (±margem) reaproveite a mesma
    interpolação do horizonte, aplicando só regra_visivel com outra margem.
    """
    _conferir_par(ceu, horizonte)
    saida = []
    for nome in ("sun", "earth"):
        az, el, rad = _corpo(ceu, nome)
        saida.append((el, rad, horizonte_em(horizonte, az)))
    return saida[0], saida[1]


def visibilidade(ceu: dict, horizonte: dict, margem_graus: float = 0.0) -> dict:
    """{"sol_visivel": bool[], "terra_visivel": bool[]} (arrays numpy).

    Um astro é visível no instante i conforme regra_visivel (qualquer parte
    do disco acima do horizonte interpolado + margem_graus).
    """
    sol, terra = _folgas(ceu, horizonte)
    return {
        "sol_visivel": regra_visivel(*sol, margem_graus),
        "terra_visivel": regra_visivel(*terra, margem_graus),
    }


# ---------------------------------------------------------------- utilidades

def _maior_sequencia(b: np.ndarray) -> int:
    """Tamanho da maior sequência contínua de True (vetorizado)."""
    if b.size == 0:
        return 0
    borda = np.diff(np.concatenate(([0], b.astype(np.int8), [0])))
    inicios = np.flatnonzero(borda == 1)
    fins = np.flatnonzero(borda == -1)
    return int((fins - inicios).max()) if inicios.size else 0


def _instante(texto: str) -> datetime:
    return datetime.fromisoformat(texto.replace("Z", "+00:00")).astimezone(timezone.utc)


def _iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def classificar(score: float, ok: float, crit: float) -> str:
    """"ideal" se score >= ok; "critico" se score < crit; senão "moderado"."""
    _conferir_limiares(ok, crit)
    if score >= ok:
        return "ideal"
    if score < crit:
        return "critico"
    return "moderado"


def _conferir_limiares(ok, crit):
    for nome, v in (("ok", ok), ("crit", crit)):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise ValueError(f"threshold {nome} must be a number (got: {v!r})")
        if not 0.0 <= v <= 1.0:
            raise ValueError(
                f"threshold {nome} must be a fraction between 0 and 1 (got: {v}); "
                "convert from percent before calling")
    if not crit < ok:
        raise ValueError(f"the critical threshold ({crit}) must be lower than the ok threshold ({ok})")


def _conferir_par(ceu, horizonte):
    if ceu.get("site") != horizonte.get("site"):
        raise ValueError(
            f"sky and horizon are from different sites: {ceu.get('site')!r} and {horizonte.get('site')!r}")


def _passos(ceu: dict, horas: float, nome: str) -> int:
    """Converte horas em nº de passos inteiro (erro se não cair na grade)."""
    if isinstance(horas, bool) or not isinstance(horas, (int, float)) or not math.isfinite(horas):
        raise ValueError(f"{nome} must be a number (got: {horas!r})")
    passo = ceu["step_min"]
    n = horas * 60 / passo
    if not math.isclose(n, round(n), abs_tol=1e-9):
        raise ValueError(f"{nome} = {horas} h is not a multiple of the sky time step ({passo} min)")
    return int(round(n))


def _janela(ceu: dict, inicio_idx, janela_h) -> tuple[int, int, int]:
    """(início, nº de passos, total de instantes), validando o alcance."""
    if isinstance(inicio_idx, bool) or not isinstance(inicio_idx, (int, np.integer)):
        raise ValueError(f"inicio_idx must be an integer (got: {inicio_idx!r})")
    inicio_idx = int(inicio_idx)
    n = _passos(ceu, janela_h, "janela_h")
    if n <= 0:
        raise ValueError(f"janela_h must be > 0 (got: {janela_h})")
    total = len(ceu["sun"]["el"])
    if inicio_idx < 0 or inicio_idx + n > total:
        ini = _instante(ceu["start"])
        passo = timedelta(minutes=ceu["step_min"])
        fim_ceu = ini + passo * total
        pedido_ini = ini + passo * inicio_idx
        raise ValueError(
            f"window out of the sky range: requested {_iso(pedido_ini)} + {janela_h} h, "
            f"but the sky for {ceu['site']} covers {_iso(ini)} to {_iso(fim_ceu)} "
            f"({total} samples of {ceu['step_min']} min)")
    return inicio_idx, n, total


def indice_de(ceu: dict, instante: datetime) -> int:
    """Índice do instante na grade do céu (para converter a data de pouso).

    Erro se o instante não cair exatamente na grade ou estiver fora dela.
    """
    if not isinstance(instante, datetime) or instante.tzinfo is None:
        raise ValueError("instante must be a timezone-aware datetime (tzinfo=timezone.utc)")
    delta = instante.astimezone(timezone.utc) - _instante(ceu["start"])
    passos = delta.total_seconds() / (ceu["step_min"] * 60)
    if not math.isclose(passos, round(passos), abs_tol=1e-9):
        raise ValueError(f"{_iso(instante)} is not on the {ceu['step_min']}-min grid of the sky")
    i = int(round(passos))
    if not 0 <= i < len(ceu["sun"]["el"]):
        raise ValueError(f"{_iso(instante)} is out of the sky range for {ceu['site']}")
    return i


def _mock(ceu, horizonte) -> bool:
    return bool(ceu.get("mock", False)) or bool(horizonte.get("mock", False))


# ---------------------------------------------------------------- métricas

def _resumo(v: np.ndarray, passo_h: float) -> dict:
    """pct e maiores sequências com/sem visibilidade de uma janela."""
    return {
        "pct": float(np.count_nonzero(v) / v.size),
        "longest_with_h": _maior_sequencia(v) * passo_h,
        "longest_without_h": _maior_sequencia(~v) * passo_h,
    }


def _diario(v: np.ndarray, inicio: datetime, step_min: int) -> list[dict]:
    """Uma entrada por bloco de 24 h a partir do início da janela.

    O último bloco pode ser parcial (janela que não é múltipla de 24 h):
    a fração usa só os instantes que existem nele.
    """
    dia = (np.arange(v.size) * step_min) // 1440
    vistos = np.bincount(dia, weights=v.astype(float))
    totais = np.bincount(dia)
    return [{"date": _iso(inicio + timedelta(days=k)), "pct": float(vistos[k] / totais[k])}
            for k in range(totais.size)]


def calcular_metricas(ceu: dict, horizonte: dict, inicio_idx: int, janela_h: float,
                      ok: float = OK_PADRAO, crit: float = CRIT_PADRAO,
                      margem_graus: float = 0.0,
                      incerteza_graus: float = INCERTEZA_PADRAO_GRAUS) -> dict:
    """Métricas de energia e comunicação numa janela do céu.

    inicio_idx: índice do primeiro instante da janela (ver indice_de).
    janela_h:   duração em horas (múltiplo do passo do céu).
    ok, crit:   limiares em fração (0–1), crit < ok.
    margem_graus: margem somada ao horizonte na regra de visibilidade.
    incerteza_graus: o score também é calculado com o horizonte
        −incerteza e +incerteza (score_max e score_min).
    """
    _conferir_limiares(ok, crit)
    i0, n, _ = _janela(ceu, inicio_idx, janela_h)
    if incerteza_graus < 0:
        raise ValueError(f"incerteza_graus must be >= 0 (got: {incerteza_graus})")

    sol, terra = _folgas(ceu, horizonte)
    janela = slice(i0, i0 + n)
    sol = tuple(a[janela] for a in sol)
    terra = tuple(a[janela] for a in terra)

    step_min = ceu["step_min"]
    passo_h = step_min / 60
    inicio = _instante(ceu["start"]) + timedelta(minutes=step_min * i0)

    def score_com(margem):
        s = regra_visivel(*sol, margem)
        t = regra_visivel(*terra, margem)
        return min(np.count_nonzero(s), np.count_nonzero(t)) / n

    s = regra_visivel(*sol, margem_graus)
    t = regra_visivel(*terra, margem_graus)
    ambos = s & t

    energia = _resumo(s, passo_h)
    energia["daily"] = _diario(s, inicio, step_min)
    comms = _resumo(t, passo_h)
    comms["daily"] = _diario(t, inicio, step_min)

    score = min(energia["pct"], comms["pct"])
    return {
        "site": ceu["site"],
        "window": {"start": _iso(inicio), "hours": n * passo_h},
        "mock": _mock(ceu, horizonte),
        "energy": energia,
        "comms": comms,
        "both": {"pct": float(np.count_nonzero(ambos) / n),
                 "longest_h": _maior_sequencia(ambos) * passo_h},
        "score": score,
        "class": classificar(score, ok, crit),
        "thresholds": {"ok": ok, "crit": crit},
        "incerteza": {
            "margem_graus": incerteza_graus,
            # Horizonte mais alto -> menos visibilidade -> score menor.
            "score_min": float(score_com(margem_graus + incerteza_graus)),
            "score_max": float(score_com(margem_graus - incerteza_graus)),
        },
    }


def serie_por_atraso(ceu: dict, horizonte: dict, inicio_idx: int, janela_h: float,
                     atrasos_dias, ok: float = OK_PADRAO, crit: float = CRIT_PADRAO,
                     margem_graus: float = 0.0) -> list[dict]:
    """[{atraso_dias, score, class}] para o simulador de atraso do pouso.

    A visibilidade é calculada UMA vez para o céu inteiro; cada atraso só
    desloca a janela. As contagens por janela saem de somas acumuladas
    (sem laço por instante), com o mesmo score de calcular_metricas.
    """
    _conferir_limiares(ok, crit)
    i0, n, total = _janela(ceu, inicio_idx, janela_h)
    atrasos = list(atrasos_dias)
    if not atrasos:
        return []

    deslocamentos = []
    for a in atrasos:
        d = _passos(ceu, a * 24, f"delay of {a} days")
        if i0 + d < 0 or i0 + d + n > total:
            _janela(ceu, i0 + d, janela_h)  # levanta o ValueError com a explicação
        deslocamentos.append(d)

    v = visibilidade(ceu, horizonte, margem_graus)
    inicios = i0 + np.asarray(deslocamentos, dtype=np.int64)

    def contagens(b):
        acum = np.concatenate(([0], np.cumsum(b, dtype=np.int64)))
        return acum[inicios + n] - acum[inicios]

    sol = contagens(v["sol_visivel"])
    terra = contagens(v["terra_visivel"])
    scores = np.minimum(sol, terra) / n
    return [{"atraso_dias": a, "score": float(sc), "class": classificar(float(sc), ok, crit)}
            for a, sc in zip(atrasos, scores)]
