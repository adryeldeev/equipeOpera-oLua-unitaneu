"""Publica o estado atual (HEAD) do projeto num Hugging Face Space (Docker).

    # PowerShell
    $env:HF_TOKEN = "hf_..."            # token com permissão "Write"
    python pipeline/tools/publicar_hf.py --space SEU_USUARIO/landerbnb

    # bash
    HF_TOKEN=hf_... python pipeline/tools/publicar_hf.py --space SEU_USUARIO/landerbnb

Por que um script: o Hugging Face recusa imagens (.jpg/.png) que não estejam
no Git LFS, inclusive no histórico. Em vez de reescrever o histórico do
GitHub, o script copia só os arquivos do commit atual (git archive HEAD)
para uma pasta temporária, cria um commit único com as imagens no LFS e
envia para o Space (substituindo o conteúdo anterior do Space).

O Space usa o Dockerfile da raiz e o cabeçalho YAML do README.md
(sdk: docker, app_port: 8001). O token NÃO é gravado em disco nem impresso.
"""

from __future__ import annotations

import argparse
import base64
import io
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
BINARIOS = ("*.jpg", "*.jpeg", "*.png", "*.gif", "*.webp", "*.ico")


def rodar(cmd, cwd, extra_env=None, ocultar=None):
    env = {**os.environ, **(extra_env or {})}
    r = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
    saida = (r.stdout + r.stderr).strip()
    if ocultar:
        saida = saida.replace(ocultar, "***")
    if r.returncode != 0:
        mostrar = " ".join(c if not (ocultar and ocultar in c) else "***" for c in cmd)
        raise SystemExit(f"falhou: {mostrar}\n{saida}")
    return saida


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Publica o projeto num Hugging Face Space (Docker).")
    p.add_argument("--space", required=True, help="USUARIO/NOME do Space, ex.: maria/landerbnb")
    p.add_argument("--ref", default="HEAD", help="commit/branch a publicar (padrão: HEAD)")
    a = p.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    token = os.environ.get("HF_TOKEN", "").strip()
    if not token:
        p.error("defina a variável de ambiente HF_TOKEN com um token de escrita do Hugging Face")
    if "/" not in a.space:
        p.error("--space deve ser USUARIO/NOME")
    usuario = a.space.split("/")[0]

    commit = rodar(["git", "rev-parse", "--short", a.ref], RAIZ)
    arquivo = subprocess.run(["git", "archive", "--format=tar", a.ref], cwd=RAIZ, capture_output=True, check=True).stdout

    with tempfile.TemporaryDirectory(prefix="hf-space-") as tmp:
        destino = Path(tmp)
        with tarfile.open(fileobj=io.BytesIO(arquivo)) as tar:
            tar.extractall(destino, filter="data")
        rodar(["git", "init", "-q", "-b", "main"], destino)
        rodar(["git", "lfs", "install", "--local"], destino)
        rodar(["git", "lfs", "track", *BINARIOS], destino)
        rodar(["git", "add", "-A"], destino)
        rodar(["git", "-c", "user.name=publicar_hf", "-c", "user.email=publicar_hf@localhost",
               "commit", "-q", "-m", f"Publica {commit} do repositório do projeto"], destino)
        n = rodar(["git", "lfs", "ls-files"], destino).count("\n") + 1
        print(f"commit {commit}: {len(list(destino.rglob('*')))} itens, {n} arquivo(s) no LFS")

        cabecalho = "Authorization: Basic " + base64.b64encode(f"{usuario}:{token}".encode()).decode()
        url = f"https://huggingface.co/spaces/{a.space}"
        print(f"enviando para {url} ...")
        rodar(["git", "-c", f"http.extraheader={cabecalho}", "push", "--force", url, "main"],
              destino, ocultar=token)
    print(f"ok. Acompanhe o build em {url} (aba Logs).")
    print(f"Site: https://{a.space.replace('/', '-').replace('_', '-').lower()}.hf.space")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
