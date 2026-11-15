"""Publica o site num Hugging Face Space ESTÁTICO (gratuito).

    # PowerShell
    $env:HF_TOKEN = "hf_..."            # token com permissão "Write"
    python pipeline/tools/publicar_hf.py --space adryelmartinss/landerbnb

    # Só montar o pacote numa pasta, sem enviar (para conferir):
    python pipeline/tools/publicar_hf.py --space x/y --so-montar saida_site

O que vai para o Space (montado a partir do commit atual, git archive HEAD):
    index.html, style.css, js/, assets/   <- web/ (sem tests/ e package.json)
    data/sites.json, data/sky/, data/horizon/
    README.md                              <- cabeçalho do Space (sdk: static)
O index.html sai com <meta name="api-base" content="static">: o site usa o
MODO ESTÁTICO (contas no navegador com web/js/calculo.js, iguais ao Python).

Imagens vão no Git LFS (o Hugging Face recusa binários fora do LFS). O
conteúdo anterior do Space é substituído (push --force). O token NÃO é
gravado em disco nem impresso.
"""

from __future__ import annotations

import argparse
import base64
import io
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
BINARIOS = ("*.jpg", "*.jpeg", "*.png", "*.gif", "*.webp", "*.ico")
META_API = '<meta name="api-base" content="">'

README_SPACE = """---
title: LanderBnB
emoji: 🌙
colorFrom: blue
colorTo: indigo
sdk: static
app_file: index.html
pinned: false
short_description: Sun & Earth visibility at lunar south pole landing sites
---

# LanderBnB: Lunar South Pole Landing Planner

Interactive planner for lunar south pole landings: will the **Sun** (power) and the **Earth**
(direct-to-Earth communication) be above the real terrain at the landing site, and what happens if
the landing slips? NASA Space Apps Challenge 2026.

This Space runs in **static mode**: every number is computed in your browser from precomputed data
(Sun/Earth ephemerides from JPL DE440 via Skyfield, terrain horizon from LRO LOLA). Source code,
pipeline, API and tests: {repo}

Published from commit `{commit}`.
"""


def rodar(cmd, cwd, ocultar=None):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    saida = (r.stdout + r.stderr).strip()
    if ocultar:
        saida = saida.replace(ocultar, "***")
    if r.returncode != 0:
        mostrar = " ".join("***" if ocultar and ocultar in c else c for c in cmd)
        raise SystemExit(f"falhou: {mostrar}\n{saida}")
    return saida


def montar(ref: str, destino: Path) -> str:
    """Monta o site estático em `destino` a partir do commit `ref`."""
    commit = rodar(["git", "rev-parse", "--short", ref], RAIZ)
    tar = subprocess.run(["git", "archive", "--format=tar", ref], cwd=RAIZ, capture_output=True, check=True).stdout
    with tempfile.TemporaryDirectory(prefix="landerbnb-src-") as src:
        src = Path(src)
        with tarfile.open(fileobj=io.BytesIO(tar)) as t:
            t.extractall(src, filter="data")
        web = src / "web"
        for item in web.iterdir():
            if item.name in ("tests", "package.json"):
                continue
            alvo = destino / item.name
            shutil.copytree(item, alvo) if item.is_dir() else shutil.copy2(item, alvo)
        (destino / "data").mkdir()
        shutil.copy2(src / "data" / "sites.json", destino / "data" / "sites.json")
        for pasta in ("sky", "horizon"):
            shutil.copytree(src / "data" / pasta, destino / "data" / pasta)

    index = destino / "index.html"
    html = index.read_text(encoding="utf-8")
    if META_API not in html:
        raise SystemExit(f"index.html sem {META_API!r}: não dá para ligar o modo estático")
    index.write_text(html.replace(META_API, '<meta name="api-base" content="static">'), encoding="utf-8")

    repo = rodar(["git", "remote", "get-url", "origin"], RAIZ).removesuffix(".git")
    (destino / "README.md").write_text(README_SPACE.format(repo=repo, commit=commit), encoding="utf-8")
    return commit


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Publica o site num Hugging Face Space estático.")
    p.add_argument("--space", required=True, help="USUARIO/NOME do Space, ex.: adryelmartinss/landerbnb")
    p.add_argument("--ref", default="HEAD", help="commit/branch a publicar (padrão: HEAD)")
    p.add_argument("--so-montar", metavar="PASTA", help="só monta o site nessa pasta (nova), sem enviar")
    a = p.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if "/" not in a.space:
        p.error("--space deve ser USUARIO/NOME")

    if a.so_montar:
        destino = Path(a.so_montar)
        if destino.exists():
            p.error(f"{destino} já existe; escolha uma pasta nova")
        destino.mkdir(parents=True)
        commit = montar(a.ref, destino)
        print(f"ok  site do commit {commit} montado em {destino}")
        return 0

    token = os.environ.get("HF_TOKEN", "").strip()
    if not token:
        p.error("defina a variável de ambiente HF_TOKEN com um token de escrita do Hugging Face")
    usuario = a.space.split("/")[0]

    with tempfile.TemporaryDirectory(prefix="hf-space-") as tmp:
        destino = Path(tmp)
        commit = montar(a.ref, destino)
        rodar(["git", "init", "-q", "-b", "main"], destino)
        rodar(["git", "lfs", "install", "--local"], destino)
        rodar(["git", "lfs", "track", *BINARIOS], destino)
        rodar(["git", "add", "-A"], destino)
        rodar(["git", "-c", "user.name=publicar_hf", "-c", "user.email=publicar_hf@localhost",
               "commit", "-q", "-m", f"Site estático do commit {commit}"], destino)
        n_lfs = len(rodar(["git", "lfs", "ls-files"], destino).splitlines())
        print(f"commit {commit}: site montado ({n_lfs} imagens no LFS)")

        cabecalho = "Authorization: Basic " + base64.b64encode(f"{usuario}:{token}".encode()).decode()
        url = f"https://huggingface.co/spaces/{a.space}"
        print(f"enviando para {url} ...")
        rodar(["git", "-c", f"http.extraheader={cabecalho}", "push", "--force", url, "main"],
              destino, ocultar=token)
    print(f"ok. Space: {url}")
    print(f"Site:  https://{a.space.replace('/', '-').replace('_', '-').lower()}.hf.space")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
