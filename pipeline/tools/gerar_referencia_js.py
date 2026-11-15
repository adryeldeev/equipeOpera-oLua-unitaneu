"""Gera web/tests/fixtures/metricas_ref.json: resultados do metrics.py (Python)
que o web/js/calculo.js (modo estático) precisa reproduzir EXATAMENTE.

    python pipeline/tools/gerar_referencia_js.py

Usa os dados reais de data/ (céu de 2027 e horizonte do LOLA). Rode de novo
se mudar metrics.py, data/sky ou data/horizon.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pipeline import metrics as mt  # noqa: E402

RAIZ = Path(__file__).resolve().parents[2]
SAIDA = RAIZ / "web" / "tests" / "fixtures" / "metricas_ref.json"
# (local, início em índice, janela em h, ok, crit, margem): cobre limiares,
# margem ≠ 0, horizonte mock (Apollo 11) e janela que não é múltipla de 24 h.
CASOS = [
    ("shackleton", 0, 720, 0.5, 0.2, 0.0),
    ("malapert", 1416, 720, 0.5, 0.2, 0.0),
    ("nobile", 3000, 500, 0.4, 0.1, 0.3),
    ("haworth", 5000, 720, 0.6, 0.3, -0.5),
    ("mons_mouton", 7000, 720, 0.5, 0.2, 0.0),
    ("apollo11", 100, 720, 0.5, 0.2, 0.0),
]


def ler(rel):
    return json.loads((RAIZ / rel).read_text(encoding="utf-8"))


def main():
    casos = []
    for site, i0, janela, ok, crit, margem in CASOS:
        ceu, hz = ler(f"data/sky/{site}.json"), ler(f"data/horizon/{site}.json")
        casos.append({
            "site": site, "inicio_idx": i0, "janela_h": janela, "ok": ok, "crit": crit, "margem": margem,
            "metricas": mt.calcular_metricas(ceu, hz, i0, janela, ok, crit, margem_graus=margem),
            "atrasos": mt.serie_por_atraso(ceu, hz, i0, janela, range(15), ok, crit, margem_graus=margem),
        })
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text(json.dumps({"casos": casos}, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"ok  {len(casos)} casos -> {SAIDA.relative_to(RAIZ)}")


if __name__ == "__main__":
    main()
