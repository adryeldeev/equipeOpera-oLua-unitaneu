"""Exportação para data/ (plano B da API) e verificação do contrato de dados.

    # Gera/atualiza data/sites.json a partir do sites.yaml e confere que
    # data/sky/<id>.json e data/horizon/<id>.json existem para cada local.
    python -m pipeline.export --sites pipeline/config/sites.yaml --out data
    python -m pipeline.export --out data --site malapert --start 2027-03-01 --days 44

    # Valida TODOS os JSON de data/ e data_mock/ contra o contrato.
    python -m pipeline.export --check

Este módulo NÃO recalcula céu nem horizonte (isso é de ephemeris.py e
horizon.py). Ele só escreve sites.json e _meta.json, sempre de forma
atômica (arquivo temporário na mesma pasta + os.replace).

Os validadores (validar_sites, validar_horizonte, validar_ceu,
validar_metricas) devolvem uma lista de erros em português; lista vazia
significa "ok". A API pode reutilizá-los.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SITES_YAML_PADRAO = RAIZ / "pipeline" / "config" / "sites.yaml"
PASTAS_CHECK_PADRAO = (RAIZ / "data", RAIZ / "data_mock")

CAMPOS_SITE = ("id", "name", "lat", "lon", "category", "mission")
N_HORIZONTE = 360
CLASSES = ("ideal", "moderado", "critico")


# ---------------------------------------------------------------- escrita

def gravar_json_atomico(caminho: Path, obj, compacto: bool = False) -> None:
    """Grava em arquivo temporário na mesma pasta e troca com os.replace.

    Quem lê (nginx, API) nunca vê um JSON pela metade.
    """
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=caminho.parent, prefix=f".{caminho.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            if compacto:
                json.dump(obj, f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            else:
                json.dump(obj, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.write("\n")
        os.replace(tmp, caminho)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


# ---------------------------------------------------------------- validação

def _eh_numero(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _numero(erros, nome, v, minimo=None, maximo=None, max_aberto=False):
    if not _eh_numero(v):
        erros.append(f"{nome}: deve ser número (recebido: {type(v).__name__})")
        return False
    if not math.isfinite(v):
        erros.append(f"{nome}: valor não finito ({v})")
        return False
    if minimo is not None and v < minimo:
        erros.append(f"{nome}: {v} < {minimo}")
        return False
    if maximo is not None and (v >= maximo if max_aberto else v > maximo):
        erros.append(f"{nome}: {v} fora do limite ({'<' if max_aberto else '<='} {maximo})")
        return False
    return True


def _lista_numeros(erros, nome, v, minimo=None, maximo=None, max_aberto=False):
    """Confere uma lista de números; agrupa os erros (não um por item)."""
    if not isinstance(v, list):
        erros.append(f"{nome}: deve ser lista")
        return None
    nao_num = [i for i, x in enumerate(v) if not _eh_numero(x)]
    if nao_num:
        erros.append(f"{nome}: {len(nao_num)} valor(es) não numérico(s), primeiro no índice {nao_num[0]}")
        return len(v)
    nan = [i for i, x in enumerate(v) if not math.isfinite(x)]
    if nan:
        erros.append(f"{nome}: {len(nan)} valor(es) NaN/infinito, primeiro no índice {nan[0]}")
    fora = [i for i, x in enumerate(v) if math.isfinite(x) and (
        (minimo is not None and x < minimo)
        or (maximo is not None and (x >= maximo if max_aberto else x > maximo)))]
    if fora:
        faixa = f"[{minimo}, {maximo}{')' if max_aberto else ']'}"
        erros.append(f"{nome}: {len(fora)} valor(es) fora de {faixa}, "
                     f"primeiro no índice {fora[0]} ({v[fora[0]]})")
    return len(v)


def _chaves(erros, obj, obrigatorias, onde=""):
    if not isinstance(obj, dict):
        erros.append(f"{onde or 'raiz'}: deve ser objeto")
        return False
    faltando = [k for k in obrigatorias if k not in obj]
    for k in faltando:
        erros.append(f"{onde}{k}: chave obrigatória ausente")
    return not faltando


def _mock(erros, obj, onde=""):
    if "mock" not in obj:
        erros.append(f"{onde}mock: chave obrigatória ausente")
    elif not isinstance(obj["mock"], bool):
        erros.append(f"{onde}mock: deve ser true/false")


def _data_iso_utc(erros, nome, v):
    if not isinstance(v, str) or not v.endswith("Z"):
        erros.append(f"{nome}: deve ser ISO 8601 UTC terminado em 'Z' (recebido: {v!r})")
        return None
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        erros.append(f"{nome}: data inválida ({v!r})")
        return None


def validar_sites(obj) -> list[str]:
    """sites.json: lista de {id, name, lat, lon, category, mission, mock}."""
    erros: list[str] = []
    if not isinstance(obj, list) or not obj:
        return ["raiz: deve ser lista não vazia de locais"]
    ids = set()
    for i, s in enumerate(obj):
        onde = f"[{i}]."
        if not _chaves(erros, s, CAMPOS_SITE, onde):
            continue
        for k in ("id", "name", "category", "mission"):
            if not isinstance(s[k], str) or not s[k]:
                erros.append(f"{onde}{k}: deve ser texto não vazio")
        _numero(erros, f"{onde}lat", s["lat"], -90, 90)
        _numero(erros, f"{onde}lon", s["lon"], -180, 180)
        _mock(erros, s, onde)
        if s["id"] in ids:
            erros.append(f"{onde}id: '{s['id']}' repetido")
        ids.add(s["id"])
    return erros


def validar_horizonte(obj) -> list[str]:
    """horizon/<id>.json: {site, az_step_deg, horizon_deg[360], mock, meta?}."""
    erros: list[str] = []
    if not _chaves(erros, obj, ("site", "az_step_deg", "horizon_deg")):
        _mock(erros, obj if isinstance(obj, dict) else {})
        return erros
    if not isinstance(obj["site"], str) or not obj["site"]:
        erros.append("site: deve ser texto não vazio")
    if _numero(erros, "az_step_deg", obj["az_step_deg"], 0) and \
            not math.isclose(obj["az_step_deg"] * N_HORIZONTE, 360.0):
        erros.append(f"az_step_deg: {obj['az_step_deg']} (com {N_HORIZONTE} valores deve ser 1)")
    n = _lista_numeros(erros, "horizon_deg", obj["horizon_deg"], -90, 90)
    if n is not None and n != N_HORIZONTE:
        erros.append(f"horizon_deg: {n} valores (esperado {N_HORIZONTE})")
    if "meta" in obj and not isinstance(obj["meta"], dict):
        erros.append("meta: deve ser objeto")
    _mock(erros, obj)
    return erros


def validar_ceu(obj) -> list[str]:
    """sky/<id>.json: {site, frame, start, step_min, sun:{az,el,rad_deg}, earth:{...}, mock}."""
    erros: list[str] = []
    if not _chaves(erros, obj, ("site", "frame", "start", "step_min", "sun", "earth")):
        _mock(erros, obj if isinstance(obj, dict) else {})
        return erros
    if not isinstance(obj["site"], str) or not obj["site"]:
        erros.append("site: deve ser texto não vazio")
    if obj["frame"] != "MOON_ME":
        erros.append(f"frame: esperado 'MOON_ME' (recebido: {obj['frame']!r})")
    _data_iso_utc(erros, "start", obj["start"])
    if isinstance(obj["step_min"], bool) or not isinstance(obj["step_min"], int) \
            or obj["step_min"] <= 0:
        erros.append(f"step_min: deve ser inteiro > 0 (recebido: {obj['step_min']!r})")
    tamanhos = {}
    for corpo in ("sun", "earth"):
        if not _chaves(erros, obj[corpo], ("az", "el", "rad_deg"), f"{corpo}."):
            continue
        c = obj[corpo]
        tamanhos[f"{corpo}.az"] = _lista_numeros(erros, f"{corpo}.az", c["az"], 0, 360, max_aberto=True)
        tamanhos[f"{corpo}.el"] = _lista_numeros(erros, f"{corpo}.el", c["el"], -90, 90)
        tamanhos[f"{corpo}.rad_deg"] = _lista_numeros(erros, f"{corpo}.rad_deg", c["rad_deg"], 0, 90)
    validos = {k: v for k, v in tamanhos.items() if v is not None}
    if len(set(validos.values())) > 1:
        erros.append("arrays de tamanhos diferentes: "
                     + ", ".join(f"{k}={v}" for k, v in validos.items()))
    elif validos and next(iter(validos.values())) == 0:
        erros.append("arrays vazios")
    _mock(erros, obj)
    return erros


def validar_meta(obj) -> list[str]:
    """_meta.json (data/ ou data/sky/): objeto com gerado_em ISO UTC."""
    erros: list[str] = []
    if _chaves(erros, obj, ("gerado_em",)):
        _data_iso_utc(erros, "gerado_em", obj["gerado_em"])
    return erros


def _validar_resumo(erros, nome, r, com_diario=True):
    chaves = ("pct", "longest_with_h", "longest_without_h") + (("daily",) if com_diario else ())
    if not _chaves(erros, r, chaves, f"{nome}."):
        return
    _numero(erros, f"{nome}.pct", r["pct"], 0, 1)
    _numero(erros, f"{nome}.longest_with_h", r["longest_with_h"], 0)
    _numero(erros, f"{nome}.longest_without_h", r["longest_without_h"], 0)
    if not isinstance(r["daily"], list) or not r["daily"]:
        erros.append(f"{nome}.daily: deve ser lista não vazia")
        return
    for i, d in enumerate(r["daily"]):
        if _chaves(erros, d, ("date", "pct"), f"{nome}.daily[{i}]."):
            _data_iso_utc(erros, f"{nome}.daily[{i}].date", d["date"])
            _numero(erros, f"{nome}.daily[{i}].pct", d["pct"], 0, 1)


def validar_metricas(obj) -> list[str]:
    """Saída de metrics.calcular_metricas (o que a API devolve ao front)."""
    erros: list[str] = []
    obrig = ("site", "window", "mock", "energy", "comms", "both", "score", "class",
             "thresholds", "incerteza")
    if not _chaves(erros, obj, obrig):
        return erros
    if not isinstance(obj["site"], str) or not obj["site"]:
        erros.append("site: deve ser texto não vazio")
    if _chaves(erros, obj["window"], ("start", "hours"), "window."):
        _data_iso_utc(erros, "window.start", obj["window"]["start"])
        _numero(erros, "window.hours", obj["window"]["hours"], 0)
    if not isinstance(obj["mock"], bool):
        erros.append("mock: deve ser true/false")
    _validar_resumo(erros, "energy", obj["energy"])
    _validar_resumo(erros, "comms", obj["comms"])
    if _chaves(erros, obj["both"], ("pct", "longest_h"), "both."):
        _numero(erros, "both.pct", obj["both"]["pct"], 0, 1)
        _numero(erros, "both.longest_h", obj["both"]["longest_h"], 0)
    score_ok = _numero(erros, "score", obj["score"], 0, 1)
    if obj["class"] not in CLASSES:
        erros.append(f"class: deve ser um de {CLASSES} (recebido: {obj['class']!r})")
    if _chaves(erros, obj["thresholds"], ("ok", "crit"), "thresholds."):
        t = obj["thresholds"]
        if _numero(erros, "thresholds.ok", t["ok"], 0, 1) and \
                _numero(erros, "thresholds.crit", t["crit"], 0, 1) and not t["crit"] < t["ok"]:
            erros.append("thresholds: crit deve ser menor que ok")
    if _chaves(erros, obj["incerteza"], ("margem_graus", "score_min", "score_max"), "incerteza."):
        inc = obj["incerteza"]
        _numero(erros, "incerteza.margem_graus", inc["margem_graus"], 0)
        if _numero(erros, "incerteza.score_min", inc["score_min"], 0, 1) and \
                _numero(erros, "incerteza.score_max", inc["score_max"], 0, 1) and score_ok and \
                not inc["score_min"] <= obj["score"] <= inc["score_max"]:
            erros.append("incerteza: esperado score_min <= score <= score_max")
    return erros


# ---------------------------------------------------------------- --check

def _ler_json(caminho: Path):
    """json.load que aceita NaN/Infinity (para poder APONTÁ-los como erro)."""
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)


def validar_arquivo(caminho: Path) -> list[str]:
    """Escolhe o validador pela posição do arquivo na pasta de dados."""
    try:
        obj = _ler_json(caminho)
    except (OSError, ValueError) as e:
        return [f"JSON ilegível: {e}"]
    nome, pasta = caminho.name, caminho.parent.name
    if nome == "_meta.json":
        return validar_meta(obj)
    if nome == "sites.json":
        return validar_sites(obj)
    if pasta in ("horizon", "sky"):
        erros = validar_horizonte(obj) if pasta == "horizon" else validar_ceu(obj)
        if isinstance(obj, dict) and obj.get("site") not in (None, caminho.stem):
            erros.append(f"site: '{obj.get('site')}' não bate com o nome do arquivo '{caminho.stem}'")
        return erros
    return ["arquivo sem contrato conhecido (esperado sites.json, _meta.json, horizon/ ou sky/)"]


def verificar_pastas(pastas) -> dict[Path, list[str]]:
    """{arquivo: [erros]} para todos os .json das pastas (recursivo)."""
    resultado: dict[Path, list[str]] = {}
    for pasta in pastas:
        pasta = Path(pasta)
        if not pasta.is_dir():
            resultado[pasta] = ["pasta não encontrada"]
            continue
        arquivos = sorted(p for p in pasta.rglob("*.json") if not p.name.startswith("."))
        ids = None
        if (pasta / "sites.json").exists():
            try:
                ids = {s["id"] for s in _ler_json(pasta / "sites.json")}
            except Exception:  # o erro já aparece na validação do próprio sites.json
                ids = None
        for arq in arquivos:
            erros = validar_arquivo(arq)
            if ids is not None and arq.parent.name in ("horizon", "sky") \
                    and arq.name != "_meta.json" and arq.stem not in ids:
                erros.append(f"local '{arq.stem}' não está em {pasta.name}/sites.json")
            resultado[arq] = erros
    return resultado


def _rel(p: Path) -> str:
    try:
        return str(Path(p).resolve().relative_to(RAIZ)).replace("\\", "/")
    except ValueError:
        return str(p)


def checar(pastas) -> int:
    resultado = verificar_pastas(pastas)
    com_erro = {p: e for p, e in resultado.items() if e}
    for p in resultado:
        print(f"{'ERRO' if resultado[p] else 'ok  '}  {_rel(p)}")
        for e in resultado[p]:
            print(f"        - {e}")
    print(f"\n{len(resultado)} arquivo(s) verificados, {len(com_erro)} com erro.")
    return 1 if com_erro else 0


# ---------------------------------------------------------------- exportação

def _data_utc(texto: str) -> datetime:
    d = datetime.fromisoformat(texto.replace("Z", "+00:00"))
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)


def _iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def _cobertura(ceu: dict) -> tuple[datetime, datetime]:
    """(primeiro instante, fim exclusivo) do céu."""
    ini = _data_utc(ceu["start"])
    return ini, ini + timedelta(minutes=ceu["step_min"] * len(ceu["sun"]["el"]))


def exportar(sites_yaml: Path, out: Path, site: str | None = None,
             inicio: datetime | None = None, dias: float | None = None) -> int:
    import yaml

    with open(sites_yaml, encoding="utf-8") as f:
        sites = yaml.safe_load(f)["sites"]
    lista = [{**{k: s[k] for k in CAMPOS_SITE}, "mock": False} for s in sites]
    erros = validar_sites(lista)
    if erros:
        print(f"erro: {sites_yaml} inválido:\n  - " + "\n  - ".join(erros))
        return 2
    if site and site not in {s["id"] for s in lista}:
        print(f"erro: site '{site}' não está em {sites_yaml}")
        return 2

    out = Path(out)
    gravar_json_atomico(out / "sites.json", lista)
    print(f"ok    {_rel(out / 'sites.json')} ({len(lista)} locais)")

    problemas = 0
    status = {}
    for s in lista:
        if site and s["id"] != site:
            continue
        info = {}
        for tipo in ("sky", "horizon"):
            arq = out / tipo / f"{s['id']}.json"
            if not arq.exists():
                print(f"FALTA {_rel(arq)}")
                problemas += 1
                info[tipo] = None
                continue
            obj = _ler_json(arq)
            erros = validar_ceu(obj) if tipo == "sky" else validar_horizonte(obj)
            if erros:
                print(f"ERRO  {_rel(arq)}: {'; '.join(erros)}")
                problemas += 1
            extra = ""
            if tipo == "sky" and not erros:
                ini, fim = _cobertura(obj)
                if inicio is not None:
                    pedido_fim = inicio + timedelta(days=dias or 0)
                    if inicio < ini or pedido_fim > fim:
                        erros = [f"cobre {_iso(ini)} a {_iso(fim)}, "
                                 f"mas foi pedido {_iso(inicio)} a {_iso(pedido_fim)}"]
                        print(f"ERRO  {_rel(arq)}: {erros[0]}")
                        problemas += 1
                extra = f" ({_iso(ini)} a {_iso(fim)})"
            info[tipo] = {"mock": bool(obj.get("mock", False)) if isinstance(obj, dict) else None}
            if not erros:
                print(f"ok    {_rel(arq)}{' [mock]' if info[tipo]['mock'] else ''}{extra}")
        status[s["id"]] = info

    meta_path = out / "_meta.json"
    meta = {}
    if meta_path.exists():
        try:
            meta = _ler_json(meta_path)
        except ValueError:
            meta = {}
    locais = dict(meta.get("locais", {})) if site else {}
    locais.update(status)
    meta.update({
        "gerado_em": _iso(datetime.now(timezone.utc)),
        "sites_fonte": _rel(Path(sites_yaml)),
        "sites": [s["id"] for s in lista],
        "locais": locais,
    })
    gravar_json_atomico(meta_path, meta)
    print(f"ok    {_rel(meta_path)}")
    if problemas:
        print(f"\n{problemas} problema(s). Gere ou atualize os arquivos com "
              "pipeline.ephemeris (céu) e pipeline.horizon (horizonte).")
        return 1
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m pipeline.export",
        description="Gera data/sites.json e confere data/sky e data/horizon; "
                    "--check valida todos os JSON contra o contrato.")
    p.add_argument("--check", action="store_true",
                   help="só valida os JSON (padrão: data/ e data_mock/)")
    p.add_argument("--dirs", nargs="+", help="pastas a validar com --check")
    p.add_argument("--sites", default=str(SITES_YAML_PADRAO))
    p.add_argument("--out", default=str(RAIZ / "data"))
    p.add_argument("--site", help="confere só este local")
    p.add_argument("--start", help="início em UTC (ex.: 2027-03-01): confere a cobertura do céu")
    p.add_argument("--days", type=float, help="dias a partir de --start")
    a = p.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if a.check:
        return checar([Path(d) for d in a.dirs] if a.dirs else PASTAS_CHECK_PADRAO)
    if (a.start is None) != (a.days is None):
        p.error("--start e --days devem ser usados juntos")
    if a.days is not None and a.days <= 0:
        p.error("--days deve ser > 0")
    inicio = _data_utc(a.start) if a.start else None
    return exportar(Path(a.sites), Path(a.out), a.site, inicio, a.days)


if __name__ == "__main__":
    raise SystemExit(main())
