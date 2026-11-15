#!/usr/bin/env python3
"""
Instala e valida o conector do painel.

    python conector_util.py usar pje        copia o conector de PJe para ~/.projurista/painel/conector/
    python conector_util.py usar modelo     copia o conector por receita (para as demais ferramentas)
    python conector_util.py validar         confere o conector, a receita e a última fila lida
    python conector_util.py validar --fila ARQ

A validação tem três partes:
  1. somente leitura — nenhuma ação de escrita na ferramenta (seletores e código);
  2. formato — a fila segue o contrato do painel;
  3. contagem — o que foi lido bate com o que a ferramenta diz ter em cada pasta.

Códigos de saída: 0 aprovado, 1 reprovado, 2 aprovado com avisos.
"""
import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parents[1] / "painel-juridico" / "scripts"))
try:
    import painel_base as pb
except ImportError:
    raise SystemExit("Não encontrei a skill painel-juridico ao lado desta. Rode o instalador do pacote.")

ORIGEM = AQUI.parent / "conectores"
TIPOS = {"pje": {"baixar": True}, "modelo": {"baixar": False}}

# Chamadas que alteram a página. Em conector escrito à mão, cliques passam por
# pb.clicar_leitura; preenchimento só no login.
PADROES_CODIGO = [
    (re.compile(r"(?<!clicar_leitura)\.(click|dblclick|tap|check|uncheck)\("), "clique direto (use pb.clicar_leitura)"),
    (re.compile(r"\.(fill|type|press|press_sequentially|select_option|set_input_files)\("), "preenchimento de campo"),
    (re.compile(r"\.(post|put|patch|delete)\(|method\s*=\s*[\"'](POST|PUT|PATCH|DELETE)", re.I), "requisição de escrita"),
    (re.compile(r"dispatch_event\(|\.submit\("), "envio de formulário"),
]


def dizer(msg: str = "") -> None:
    print(msg, flush=True)


def _hash(arq: Path) -> str:
    return hashlib.sha256(arq.read_bytes()).hexdigest()


def usar(tipo: str) -> int:
    origem = ORIGEM / tipo
    if not origem.is_dir():
        dizer(f"ERRO: conector '{tipo}' não acompanha o pacote.")
        return 1
    destino = pb.dir_conector()
    receita = destino / "receita.json"
    guardada = receita.read_bytes() if receita.is_file() else None
    for velho in destino.iterdir():
        if velho.is_file():
            velho.unlink()
        elif velho.name == "__pycache__":
            shutil.rmtree(velho, ignore_errors=True)
    for arq in origem.iterdir():
        if arq.is_file() and arq.suffix in (".py", ".json"):
            shutil.copy2(arq, destino / arq.name)
            pb.restringir(destino / arq.name)
    if tipo == "modelo" and guardada:
        receita.write_bytes(guardada)       # reinstalar o motor não apaga a receita do usuário
    conf = pb.carregar()
    conf["conector"] = {"arquivo": "conector.py", "tipo": tipo, "baixar": TIPOS[tipo]["baixar"]}
    pb.gravar(conf)
    dizer(f"Conector '{tipo}' instalado em {destino}.")
    if tipo == "modelo" and not receita.is_file():
        dizer("Falta escrever a receita: copie receita.exemplo.json para receita.json e ajuste os seletores.")
    return 0


def _strings(no, caminho=""):
    if isinstance(no, dict):
        for k, v in no.items():
            if not str(k).startswith("_"):
                yield from _strings(v, f"{caminho}.{k}" if caminho else str(k))
    elif isinstance(no, list):
        for i, v in enumerate(no):
            yield from _strings(v, f"{caminho}[{i}]")
    elif isinstance(no, str):
        yield caminho, no


def checar_receita(arq: Path) -> tuple:
    erros, avisos = [], []
    try:
        receita = json.loads(arq.read_text(encoding="utf-8"))
    except ValueError as exc:
        return [f"receita ilegível: {exc}"], []
    if not (receita.get("logado") or {}):
        erros.append("receita sem a seção 'logado'")
    if not (receita.get("pastas") or {}).get("seletor") and not receita.get("pastas_fixas"):
        erros.append("receita sem 'pastas.seletor' nem 'pastas_fixas'")
    lista = receita.get("lista") or {}
    if not lista.get("linha") or not lista.get("identificador"):
        erros.append("receita sem 'lista.linha' ou 'lista.identificador'")
    for caminho, texto in _strings(receita):
        if caminho.startswith("login."):
            continue
        clicavel = ("clicar" in caminho or "proximo" in caminho or caminho.endswith("pastas.seletor"))
        if clicavel and pb.texto_proibido(texto):
            erros.append(f"{caminho}: o seletor '{texto[:60]}' aponta para ação de escrita")
    if not (receita.get("paginacao") or {}):
        avisos.append("receita sem 'paginacao': só a primeira página de cada pasta será lida")
    if not lista.get("total") and not (receita.get("pastas") or {}).get("quantidade"):
        avisos.append("receita sem contador ('lista.total' ou 'pastas.quantidade'): não há como provar que a leitura foi completa")
    return erros, avisos


def checar_codigo(destino: Path) -> tuple:
    erros, avisos = [], []
    for arq in sorted(destino.glob("*.py")):
        original = next((ORIGEM / t / arq.name for t in TIPOS if (ORIGEM / t / arq.name).is_file()
                         and _hash(ORIGEM / t / arq.name) == _hash(arq)), None)
        if original:
            continue                         # arquivo idêntico ao que acompanha o pacote
        em_login = False
        for n, linha in enumerate(arq.read_text(encoding="utf-8").splitlines(), 1):
            limpa = linha.split("#", 1)[0]
            if re.match(r"\s*def ", limpa):
                em_login = bool(re.search(r"def \w*(login|preencher|entrar|autentic)\w*\(", limpa))
            for padrao, rotulo in PADROES_CODIGO:
                if padrao.search(limpa):
                    if em_login and rotulo in ("preenchimento de campo", "clique direto (use pb.clicar_leitura)"):
                        continue
                    erros.append(f"{arq.name}:{n}: {rotulo} — {limpa.strip()[:80]}")
        avisos.append(f"{arq.name} foi escrito ou alterado para este usuário: revise antes de confiar")
    return erros, avisos


def checar_fila(arq: Path) -> tuple:
    erros, avisos = [], []
    if not arq.is_file():
        return [], [f"ainda não há fila lida ({arq}): rode o conector com 'listar'"]
    try:
        fila = json.loads(arq.read_text(encoding="utf-8"))
    except ValueError as exc:
        return [f"fila ilegível: {exc}"], []
    erros += pb.validar_fila(fila)
    if erros:
        return erros, avisos
    regex = pb.regex_identificador()
    fora = [i["identificador"] for i in fila["itens"] if not regex.fullmatch(str(i["identificador"]))]
    if fora:
        erros.append(f"{len(fora)} identificador(es) fora do padrão configurado (ex.: {fora[0]!r})")
    if not fila["itens"]:
        avisos.append("a fila veio vazia: confirme na ferramenta se as pastas estão mesmo sem processos")
    for p in fila["pastas"]:
        if p.get("esperado") is None:
            avisos.append(f"pasta '{p['nome']}': sem contador para conferir ({p['enumerados']} lido(s))")
        elif not p["completo"]:
            avisos.append(f"pasta '{p['nome']}': {p['enumerados']} lido(s) de {p['esperado']} — leitura parcial")
        elif p["enumerados"] > int(p["esperado"]):
            avisos.append(f"pasta '{p['nome']}': {p['enumerados']} lido(s), mas a ferramenta indica {p['esperado']}")
        for a in p.get("avisos") or []:
            avisos.append(f"pasta '{p['nome']}': {a}")
    sem_campos = sum(1 for i in fila["itens"] if not i.get("campos"))
    if fila["itens"] and sem_campos == len(fila["itens"]):
        avisos.append("nenhum item trouxe campos além do identificador")
    return erros, avisos


def validar(arq_fila: Path) -> int:
    conector = pb.caminho_conector()
    if not conector or not conector.is_file():
        dizer("REPROVADO: nenhum conector instalado (use: conector_util.py usar pje|modelo).")
        return 1
    erros, avisos = checar_codigo(conector.parent)
    receita = conector.parent / "receita.json"
    tipo = (pb.carregar().get("conector") or {}).get("tipo")
    if tipo == "modelo" or receita.is_file():
        if not receita.is_file():
            erros.append("falta receita.json")
        else:
            e, a = checar_receita(receita)
            erros += e
            avisos += a
    e, a = checar_fila(arq_fila)
    erros += e
    avisos += a
    for linha in erros:
        dizer(f"  ERRO  {linha}")
    for linha in avisos:
        dizer(f"  aviso {linha}")
    if erros:
        dizer(f"REPROVADO: {len(erros)} erro(s). O conector não deve ser ligado ao painel assim.")
        return 1
    dizer("APROVADO" + (f" com {len(avisos)} aviso(s)." if avisos else "."))
    return 2 if avisos else 0


def main() -> int:
    pb.utf8_no_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    u = sub.add_parser("usar")
    u.add_argument("tipo", choices=sorted(TIPOS))
    v = sub.add_parser("validar")
    v.add_argument("--fila", default=None)
    args = ap.parse_args()
    if args.cmd == "usar":
        return usar(args.tipo)
    return validar(Path(args.fila).expanduser() if args.fila else pb.arq_fila())


if __name__ == "__main__":
    raise SystemExit(main())
