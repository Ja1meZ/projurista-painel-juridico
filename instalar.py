#!/usr/bin/env python3
"""
Instalador do Painel Jurídico (Projurista).

    python instalar.py                   instala as skills, os comandos e as dependências
    python instalar.py --sem-dependencias   só copia skills e comandos
    python instalar.py --dependencias    só cria o ambiente Python e instala o navegador
    python instalar.py --sim             não faz perguntas

Não pede senha nem dados do seu trabalho: isso é feito depois, em conversa, pela skill
/painel-criar, dentro do Claude Code.
"""
import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
CLAUDE = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
PROJURISTA = Path.home() / ".projurista"
SKILLS = ("painel-criar", "painel-juridico")
IGNORAR = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store")


def diga(msg: str = "") -> None:
    print(msg, flush=True)


def confirmar(pergunta: str, sim: bool) -> bool:
    if sim or not sys.stdin.isatty():
        return True
    return input(f"{pergunta} [S/n] ").strip().lower() in ("", "s", "sim", "y")


def copiar_com_backup(origem: Path, destino: Path, carimbo: str) -> str:
    nota = "instalado"
    if destino.exists():
        guarda = CLAUDE / "backups-projurista" / carimbo / destino.name
        guarda.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(destino), str(guarda))
        nota = f"atualizado (versão anterior em {guarda})"
    if origem.is_dir():
        shutil.copytree(origem, destino, ignore=IGNORAR)
    else:
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origem, destino)
    return nota


def python_do_venv(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def instalar_dependencias() -> bool:
    venv = PROJURISTA / "venv"
    py = python_do_venv(venv)
    try:
        if not py.is_file():
            diga(f"Criando o ambiente Python em {venv} ...")
            PROJURISTA.mkdir(parents=True, exist_ok=True)
            subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
        diga("Instalando as dependências (pode levar alguns minutos) ...")
        subprocess.run([str(py), "-m", "pip", "install", "--quiet", "--upgrade", "pip"], check=True)
        subprocess.run([str(py), "-m", "pip", "install", "--quiet", "-r",
                        str(RAIZ / "requirements.txt")], check=True)
        diga("Instalando o navegador Chromium do Playwright ...")
        subprocess.run([str(py), "-m", "playwright", "install", "chromium"], check=True)
    except (subprocess.CalledProcessError, OSError) as exc:
        diga(f"ERRO ao instalar dependências: {exc}")
        diga("As skills foram copiadas. Corrija o problema e rode: python instalar.py --dependencias")
        return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dependencias", action="store_true")
    ap.add_argument("--sem-dependencias", action="store_true")
    ap.add_argument("--sim", action="store_true")
    args = ap.parse_args()
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if sys.version_info < (3, 9):
        diga("É preciso Python 3.9 ou mais novo.")
        return 1

    if args.dependencias:
        return 0 if instalar_dependencias() else 1

    diga("Painel Jurídico — Projurista")
    diga(f"As skills vão para {CLAUDE / 'skills'} e os comandos para {CLAUDE / 'commands'}.")
    if not confirmar("Continuar?", args.sim):
        return 1
    carimbo = datetime.now().strftime("%Y%m%d-%H%M%S")
    for nome in SKILLS:
        nota = copiar_com_backup(RAIZ / "skills" / nome, CLAUDE / "skills" / nome, carimbo)
        diga(f"  skill {nome}: {nota}")
    for arq in sorted((RAIZ / "commands").glob("*.md")):
        nota = copiar_com_backup(arq, CLAUDE / "commands" / arq.name, carimbo)
        diga(f"  comando /{arq.stem}: {nota}")

    ok = True
    if not args.sem_dependencias:
        ok = instalar_dependencias()

    diga()
    diga("Pronto." if ok else "Instalação parcial (veja o erro acima).")
    diga("Próximo passo: abra o Claude Code e digite  /painel-criar")
    diga("Ele vai perguntar qual ferramenta você usa, como entra nela e o que quer ver no painel.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
