#!/usr/bin/env python3
"""Gera em dist/ o ZIP de entrega.

Uso:  python3 ferramentas/empacotar.py [--versao 1.0.1]

Se existir ferramentas/varredura_local.py (arquivo particular de quem mantém o pacote, fora
do controle de versão), ele é executado antes e o empacotamento só segue se passar.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
FORA = {"__pycache__", ".DS_Store"}
NOME = "Projurista-Painel-Juridico"


def arquivos(base: Path):
    for arq in sorted(base.rglob("*")):
        if arq.is_file() and not (FORA & set(arq.parts)) and arq.suffix != ".pyc":
            yield arq


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--versao", default="1.0.1")
    a = ap.parse_args()

    varredura = RAIZ / "ferramentas/varredura_local.py"
    if varredura.exists() and subprocess.run([sys.executable, str(varredura)]).returncode != 0:
        print("\nEmpacotamento cancelado: a varredura local reprovou.", file=sys.stderr)
        return 1

    dist = RAIZ / "dist"
    dist.mkdir(exist_ok=True)
    for antigo in list(dist.glob("*.skill")) + list(dist.glob("*.zip")):
        antigo.unlink()

    pacote = dist / f"{NOME}-v{a.versao}.zip"
    topo = Path(f"{NOME}-v{a.versao}")
    with zipfile.ZipFile(pacote, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.write(RAIZ / "README.md", topo / "LEIA-ME.md")
        for nome in ("docs", "skills", "commands"):
            for arq in arquivos(RAIZ / nome):
                z.write(arq, topo / arq.relative_to(RAIZ))
        for nome in ("instalar.py", "instalar.sh", "instalar.ps1", "requirements.txt", "LICENSE"):
            z.write(RAIZ / nome, topo / nome)
    print(f"  {pacote.name}: {pacote.stat().st_size / 1e6:.2f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
