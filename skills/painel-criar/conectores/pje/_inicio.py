"""Localiza a base do Painel Jurídico (skill painel-juridico) para os conectores."""
import os
import sys
from pathlib import Path


def localizar() -> None:
    candidatos = []
    if os.environ.get("PAINEL_BASE_DIR"):
        candidatos.append(Path(os.environ["PAINEL_BASE_DIR"]))
    raiz_claude = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    candidatos.append(raiz_claude / "skills" / "painel-juridico" / "scripts")
    aqui = Path(__file__).resolve()
    candidatos += [p / "skills" / "painel-juridico" / "scripts" for p in aqui.parents]
    for c in candidatos:
        if (c / "painel_base.py").is_file():
            if str(c) not in sys.path:
                sys.path.insert(0, str(c))
            return
    raise SystemExit("Não encontrei a skill painel-juridico. Rode o instalador do pacote.")


localizar()
