"""Efemérides: posição do Sol e da Terra vistos de um local na superfície da Lua.

Uso como BIBLIOTECA (é o que a API usa):

    from pipeline.ephemeris import carregar_recursos, gerar_ceu, intervalo_suportado
    carregar_recursos()                      # uma vez, no startup
    ceu = gerar_ceu(site, datetime(2027, 1, 1, tzinfo=timezone.utc), dias=30, passo_min=60)

Nada aqui lê ou escreve em data/. A CLI (fim do arquivo) só grava um cache.

Kernels (baixados para cache/, nunca versionados):
    de440s.bsp                 posições de Sol, Terra e Lua (DE440, 1849–2150)
    moon_pa_de440_200625.bpc   orientação da Lua (eixos principais, DE440)
    moon_de440_250416.tf       define o frame MOON_ME_DE440_ME421

Referencial: MOON_ME_DE440_ME421 = "Mean Earth/Polar Axis" com orientação
do DE440, alinhado ao ME do DE421 a ~1 m (segundo o próprio .tf). É o
referencial dos DEMs do LOLA, por isso a saída diz frame "MOON_ME".
O alias "MOON_ME" do .tf não é resolvido pelo Skyfield, então usamos o
nome completo.

Física / convenções:
- Lua esférica, R = 1737,4 km; vertical local = direção radial.
- Azimute: a partir do Norte, sentido horário (Leste = 90°), em [0, 360).
- Elevação: ângulo acima do plano perpendicular à vertical local.
  Sem refração (não há atmosfera). Não considera relevo: o horizonte do
  terreno é responsabilidade de horizon.py.
- observe() inclui tempo de luz; apparent() inclui aberração e deflexão.
- altaz() do Skyfield funciona para observador na Lua (exemplo "Observing
  from a Moon location" da documentação). Conferido nos testes contra uma
  rotação manual para leste-norte-cima.
- Raio angular aparente = asin(R_corpo / d), d = distância local–corpo.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parents[1]
CACHE_PADRAO = RAIZ / "cache"

KERNEL_EFEMERIDES = "de440s.bsp"
KERNEL_PCK = "moon_pa_de440_200625.bpc"
KERNEL_FK = "moon_de440_250416.tf"
URL_NAIF = "https://naif.jpl.nasa.gov/pub/naif/generic_kernels/"
URLS = {
    KERNEL_EFEMERIDES: URL_NAIF + "spk/planets/de440s.bsp",
    KERNEL_PCK: URL_NAIF + "pck/moon_pa_de440_200625.bpc",
    KERNEL_FK: URL_NAIF + "fk/satellites/moon_de440_250416.tf",
}
FRAME_SPICE = "MOON_ME_DE440_ME421"
FRAME_CONTRATO = "MOON_ME"

R_LUA_KM = 1737.4
R_SOL_KM = 696_000.0
R_TERRA_KM = 6_378.0

PASSO_MIN_LIMITES = (1, 1440)
MAX_INSTANTES = 100_000
# Margem nas pontas do intervalo: observe() procura o corpo no passado
# (tempo de luz: ~1,3 s para a Terra, ~500 s para o Sol). Um dia sobra.
MARGEM = timedelta(days=1)


# ---------------------------------------------------------------- exceções

class ErroEfemeride(Exception):
    """Base dos erros deste módulo."""


class ParametroInvalido(ErroEfemeride, ValueError):
    """Entrada inválida (site, dias, passo, número de instantes)."""


class ForaDoIntervalo(ErroEfemeride, ValueError):
    """Período fora da cobertura dos kernels."""

    def __init__(self, mensagem, inicio_suportado, fim_suportado):
        super().__init__(mensagem)
        self.inicio_suportado = inicio_suportado
        self.fim_suportado = fim_suportado


# ---------------------------------------------------------------- recursos

@dataclass(frozen=True)
class Recursos:
    ts: object          # skyfield Timescale
    lua: object         # corpos do DE440
    sol: object
    terra: object
    pc: object          # PlanetaryConstants (para criar locais)
    frame: object       # frame MOON_ME
    inicio: datetime    # cobertura útil (UTC, já com margem)
    fim: datetime
    kernels: tuple


_recursos: Recursos | None = None
_trava = threading.Lock()


def carregar_recursos(cache_dir: str | Path | None = None, baixar: bool = True) -> Recursos:
    """Carrega kernels e frame UMA vez (singleton, thread-safe).

    baixar=True: baixa para cache/ os kernels que faltarem (~45 MB, só na
    primeira vez). baixar=False: levanta FileNotFoundError se faltar algum.
    """
    global _recursos
    if _recursos is not None:
        return _recursos
    with _trava:
        if _recursos is None:  # outra thread pode ter carregado enquanto esperávamos
            _recursos = _carregar(Path(cache_dir) if cache_dir else CACHE_PADRAO, baixar)
    return _recursos


def _carregar(cache: Path, baixar: bool) -> Recursos:
    from skyfield.api import Loader
    from skyfield.planetarylib import PlanetaryConstants

    faltando = [k for k in URLS if not (cache / k).exists()]
    if faltando and not baixar:
        raise FileNotFoundError(
            f"Kernels ausentes em {cache}: {', '.join(faltando)}. "
            "Rode carregar_recursos(baixar=True) ou a CLI uma vez para baixá-los.")
    cache.mkdir(parents=True, exist_ok=True)
    carregar = Loader(str(cache), verbose=False)
    for nome in faltando:
        carregar.download(URLS[nome], filename=nome)

    ts = carregar.timescale(builtin=True)
    eph = carregar(KERNEL_EFEMERIDES)
    pc = PlanetaryConstants()
    pc.read_text(carregar(KERNEL_FK))
    pc.read_binary(carregar(KERNEL_PCK))
    # Lua esférica (o .tf não traz raios). Unidade: km.
    pc.variables["BODY301_RADII"] = [R_LUA_KM, R_LUA_KM, R_LUA_KM]

    # Cobertura do .bsp: interseção de todos os segmentos (JD TDB).
    ini_jd = max(s.start_jd for s in eph.spk.segments)
    fim_jd = min(s.end_jd for s in eph.spk.segments)

    # O .bpc do DE440 tem DOIS segmentos (1549–2426 e 2426–2650) e o
    # Skyfield guarda só o último lido, que não cobre o nosso período.
    # Escolhemos explicitamente o segmento que cobre o .bsp inteiro.
    # (_segment_list e o argumento _segment são internos do Skyfield 1.4x;
    # se mudarem numa versão futura, os testes quebram e avisam.)
    id_tk = pc.variables[f"FRAME_{FRAME_SPICE}"]
    id_pck = pc.variables[f"FRAME_{pc.variables[f'TKFRAME_{id_tk}_RELATIVE']}"]
    candidatos = [s for s in pc._segment_list
                  if s.body == id_pck and s.initial_jd <= ini_jd and s.final_jd >= fim_jd]
    if not candidatos:
        raise RuntimeError(f"Nenhum segmento de {KERNEL_PCK} cobre {KERNEL_EFEMERIDES}")
    frame = pc.build_frame(id_tk, _segment=candidatos[0])

    inicio = ts.tdb_jd(ini_jd).utc_datetime() + MARGEM
    fim = ts.tdb_jd(fim_jd).utc_datetime() - MARGEM
    # Arredonda para o dia inteiro, para um intervalo legível na API/front.
    inicio = datetime(inicio.year, inicio.month, inicio.day, tzinfo=timezone.utc) + timedelta(days=1)
    fim = datetime(fim.year, fim.month, fim.day, tzinfo=timezone.utc)

    rec = Recursos(ts=ts, lua=eph["moon"], sol=eph["sun"], terra=eph["earth"],
                   pc=pc, frame=frame, inicio=inicio, fim=fim,
                   kernels=(KERNEL_EFEMERIDES, KERNEL_PCK, KERNEL_FK))

    # Aquecimento: força a leitura dos segmentos agora (no startup), e não
    # na primeira requisição concorrente.
    _calcular(rec, -89.9, 0.0, rec.ts.utc(2027, 1, 1, np.arange(2)))
    return rec


def intervalo_suportado() -> tuple[datetime, datetime]:
    """(início, fim) em UTC em que gerar_ceu aceita instantes."""
    rec = carregar_recursos()
    return rec.inicio, rec.fim


# ---------------------------------------------------------------- cálculo

def _calcular(rec: Recursos, lat: float, lon: float, t):
    """Arrays de az, el (graus) e raio angular (graus) do Sol e da Terra."""
    # Ponto na superfície (altitude 0 sobre a esfera) no frame MOON_ME.
    # build_latlon_degrees usa lon LESTE positiva, como o contrato.
    local = rec.lua + rec.pc.build_latlon_degrees(rec.frame, lat, lon)
    posicao = local.at(t)  # vetorizado: todos os instantes de uma vez
    saida = {}
    for nome, corpo, raio in (("sun", rec.sol, R_SOL_KM), ("earth", rec.terra, R_TERRA_KM)):
        aparente = posicao.observe(corpo).apparent()
        el, az, dist = aparente.altaz()  # sem refração (argumentos omitidos)
        saida[nome] = (az.degrees, el.degrees, np.degrees(np.arcsin(raio / dist.km)))
    return saida


def _numero(valor, nome):
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not math.isfinite(valor):
        raise ParametroInvalido(f"{nome} deve ser um número finito (recebido: {valor!r})")
    return float(valor)


def _validar(site, inicio, dias, passo_min):
    if not isinstance(site, dict):
        raise ParametroInvalido("site deve ser um dict com id, lat e lon")
    for chave in ("id", "lat", "lon"):
        if chave not in site:
            raise ParametroInvalido(f"site sem o campo obrigatório '{chave}'")
    lat = _numero(site["lat"], "site.lat")
    lon = _numero(site["lon"], "site.lon")
    if not -90 <= lat <= 90:
        raise ParametroInvalido(f"site.lat fora de [-90, 90]: {lat}")
    if not -180 <= lon <= 360:
        raise ParametroInvalido(f"site.lon fora de [-180, 360]: {lon}")

    if not isinstance(inicio, datetime):
        raise ParametroInvalido("inicio deve ser um datetime")
    if inicio.tzinfo is None or inicio.utcoffset() is None:
        raise ParametroInvalido("inicio deve ter fuso horário (use tzinfo=timezone.utc)")

    dias = _numero(dias, "dias")
    if dias <= 0:
        raise ParametroInvalido(f"dias deve ser > 0 (recebido: {dias})")

    if isinstance(passo_min, bool) or not isinstance(passo_min, int):
        raise ParametroInvalido(f"passo_min deve ser inteiro (recebido: {passo_min!r})")
    lo, hi = PASSO_MIN_LIMITES
    if not lo <= passo_min <= hi:
        raise ParametroInvalido(f"passo_min deve estar entre {lo} e {hi} (recebido: {passo_min})")

    # Instantes: início, início+passo, ... estritamente antes de início+dias.
    n = math.ceil(round(dias * 1440 / passo_min, 9))
    if n > MAX_INSTANTES:
        raise ParametroInvalido(
            f"{n} instantes excedem o máximo de {MAX_INSTANTES}; aumente o passo ou reduza os dias")
    return lat, lon, n


def gerar_ceu(site: dict, inicio: datetime, dias: float, passo_min: int) -> dict:
    """Sol e Terra vistos de `site` em `inicio + k*passo_min`, k = 0..n-1.

    n = ceil(dias*1440/passo_min) (o fim é exclusivo: 30 dias em passo de
    60 min dão 720 instantes). Não toca em disco. Segundos fracionários de
    `inicio` são descartados para o instante bater com o "start" da saída.
    """
    lat, lon, n = _validar(site, inicio, dias, passo_min)
    rec = carregar_recursos()

    inicio = inicio.astimezone(timezone.utc).replace(microsecond=0)
    fim = inicio + timedelta(minutes=passo_min * (n - 1))
    if inicio < rec.inicio or fim > rec.fim:
        raise ForaDoIntervalo(
            f"Período {inicio:%Y-%m-%d %H:%M} – {fim:%Y-%m-%d %H:%M} UTC fora do intervalo "
            f"suportado ({rec.inicio:%Y-%m-%d} a {rec.fim:%Y-%m-%d} UTC)",
            rec.inicio, rec.fim)

    # Um único objeto Time com todos os instantes (o Skyfield normaliza os
    # minutos excedentes para horas/dias).
    minutos = inicio.minute + np.arange(n) * passo_min
    t = rec.ts.utc(inicio.year, inicio.month, inicio.day, inicio.hour, minutos, inicio.second)

    calc = _calcular(rec, lat, lon, t)
    saida = {
        "site": site["id"],
        "frame": FRAME_CONTRATO,
        "start": inicio.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "step_min": passo_min,
    }
    for nome in ("sun", "earth"):
        az, el, raio = calc[nome]
        # mod depois do round: 359,99997 viraria 360.0, fora de [0, 360).
        # "+ 0.0" troca -0.0 por 0.0 (JSON mais limpo e estável).
        saida[nome] = {
            "az": (np.mod(np.round(az, 4), 360.0) + 0.0).tolist(),
            "el": (np.round(el, 4) + 0.0).tolist(),
            "rad_deg": np.round(raio, 5).tolist(),
        }
    saida["mock"] = False
    return saida
