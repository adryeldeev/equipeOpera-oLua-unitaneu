"""Testes de pipeline/export.py (--check e exportação). Sem rede.

    python -m pytest pipeline/tests/test_export.py -v
"""

import json
import shutil
from pathlib import Path

import pytest

from pipeline import export as ex

RAIZ = Path(__file__).resolve().parents[2]
MOCK = RAIZ / "data_mock"


def _ler(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def _gravar(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding="utf-8")  # json.dumps escreve NaN se houver


@pytest.fixture
def pasta_valida(tmp_path):
    """Cópia de data_mock/ (válida) numa pasta temporária."""
    destino = tmp_path / "dados"
    shutil.copytree(MOCK, destino)
    return destino


def test_check_passa_nos_dados_do_repositorio(capsys):
    assert ex.main(["--check"]) == 0
    assert "0 com erro" in capsys.readouterr().out


def test_check_passa_na_copia_valida(pasta_valida):
    assert ex.main(["--check", "--dirs", str(pasta_valida)]) == 0


# 7. --check detecta 359 valores, NaN e mock ausente --------------------------

def test_check_detecta_erros(pasta_valida, capsys):
    h = _ler(pasta_valida / "horizon" / "malapert.json")
    h["horizon_deg"] = h["horizon_deg"][:359]
    _gravar(pasta_valida / "horizon" / "malapert.json", h)

    c = _ler(pasta_valida / "sky" / "nobile.json")
    c["sun"]["el"][5] = float("nan")
    _gravar(pasta_valida / "sky" / "nobile.json", c)

    h = _ler(pasta_valida / "horizon" / "haworth.json")
    del h["mock"]
    _gravar(pasta_valida / "horizon" / "haworth.json", h)

    assert ex.main(["--check", "--dirs", str(pasta_valida)]) != 0
    res = ex.verificar_pastas([pasta_valida])
    erros = {p.relative_to(pasta_valida).as_posix(): e for p, e in res.items() if e}
    assert set(erros) == {"horizon/malapert.json", "sky/nobile.json", "horizon/haworth.json"}
    assert any("359 valores" in e for e in erros["horizon/malapert.json"])
    assert any("NaN" in e and "sun.el" in e for e in erros["sky/nobile.json"])
    assert any(e.startswith("mock") for e in erros["horizon/haworth.json"])
    saida = capsys.readouterr().out
    assert "3 com erro" in saida


def test_check_outras_regras(pasta_valida):
    c = _ler(pasta_valida / "sky" / "malapert.json")
    c["earth"]["az"][0] = 360.0          # fora de [0, 360)
    c["sun"]["rad_deg"] = c["sun"]["rad_deg"][:-1]  # tamanhos diferentes
    c["step_min"] = "60"                 # tipo errado
    _gravar(pasta_valida / "sky" / "malapert.json", c)
    s = _ler(pasta_valida / "sites.json")
    s[1]["id"] = s[0]["id"]              # id repetido
    _gravar(pasta_valida / "sites.json", s)
    _gravar(pasta_valida / "sky" / "desconhecido.json", {"x": 1})

    res = {p.relative_to(pasta_valida).as_posix(): e
           for p, e in ex.verificar_pastas([pasta_valida]).items()}
    ceu = " | ".join(res["sky/malapert.json"])
    assert "earth.az" in ceu and "tamanhos diferentes" in ceu and "step_min" in ceu
    assert any("repetido" in e for e in res["sites.json"])
    assert any("não está em" in e for e in res["sky/desconhecido.json"])


# Exportação ------------------------------------------------------------------

def test_exportar_grava_sites_e_meta(tmp_path, capsys):
    out = tmp_path / "data"
    for tipo in ("sky", "horizon"):
        shutil.copytree(MOCK / tipo, out / tipo)
    rc = ex.main(["--out", str(out)])
    assert rc == 0, capsys.readouterr().out
    sites = _ler(out / "sites.json")
    assert [s["id"] for s in sites] == ["shackleton", "malapert", "nobile", "haworth", "mons_mouton", "apollo11"]
    assert all(s["mock"] is False for s in sites)
    meta = _ler(out / "_meta.json")
    assert meta["gerado_em"].endswith("Z")
    assert meta["locais"]["malapert"] == {"sky": {"mock": True}, "horizon": {"mock": True}}
    assert not list(out.rglob("*.tmp"))  # nada de temporário largado
    assert ex.main(["--check", "--dirs", str(out)]) == 0


def test_exportar_aponta_arquivo_faltando(tmp_path, capsys):
    out = tmp_path / "data"
    shutil.copytree(MOCK / "sky", out / "sky")
    (out / "horizon").mkdir()
    assert ex.main(["--out", str(out), "--site", "malapert"]) == 1
    assert "FALTA" in capsys.readouterr().out


def test_exportar_confere_cobertura(tmp_path, capsys):
    out = tmp_path / "data"
    for tipo in ("sky", "horizon"):
        shutil.copytree(MOCK / tipo, out / tipo)
    # O mock cobre 30 dias a partir de 2027-01-01.
    assert ex.main(["--out", str(out), "--start", "2027-01-05", "--days", "10"]) == 0
    capsys.readouterr()
    assert ex.main(["--out", str(out), "--start", "2027-01-25", "--days", "10"]) == 1
    assert "foi pedido" in capsys.readouterr().out


def test_gravacao_atomica_nao_deixa_lixo_em_erro(tmp_path):
    with pytest.raises(ValueError):
        ex.gravar_json_atomico(tmp_path / "x.json", {"v": float("nan")})
    assert list(tmp_path.iterdir()) == []
