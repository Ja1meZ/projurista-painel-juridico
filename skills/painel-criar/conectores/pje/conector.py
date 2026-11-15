#!/usr/bin/env python3
"""
Conector do PJe para o Painel Jurídico — somente leitura.

Serve aos tribunais em que o PJe oferece o "Painel do Usuário Interno" com pastas de
tarefa. Foi validado em um tribunal; o PJe muda de versão e de tela de login de um
tribunal para outro, por isso comece sempre por `sondar`.

    python conector.py sondar [--perfil "texto da lotação"] [--saida ARQ]
    python conector.py listar [--saida ARQ]
    python conector.py baixar <número> [--destino PASTA]

Códigos de saída: 0 completo, 1 erro, 2 parcial.
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))

import _inicio  # noqa: E402,F401
import painel_base as pb  # noqa: E402

CAMPOS = ["classe", "assunto", "orgao", "partes", "etiquetas", "prioridade",
          "data_chegada", "dias_na_tarefa", "ultima_movimentacao", "sigilo"]


def dizer(msg: str = "") -> None:
    print(msg, flush=True)


def sondar(args) -> int:
    pb.garantir_ambiente("playwright")
    from pje_painel import PainelPJe
    import tarefas_pje as tp

    saida = Path(args.saida).expanduser() if args.saida else pb.dir_dados() / "sondagem.json"
    resultado = {"ok": False, "sistema": "pje", "campos": CAMPOS, "perfis": [],
                 "perfil_atual": "", "pastas": [], "baixar": True, "avisos": []}
    painel = PainelPJe(perfil=(args.perfil or ""), log=dizer, headless=args.headless)
    try:
        painel.iniciar()
        if not painel.login(espera_2fa=args.espera_login):
            resultado["avisos"].append("login não concluído")
            return 1
        try:
            perfis = painel.listar_perfis()
            resultado["perfis"] = perfis.get("opcoes", [])
            resultado["perfil_atual"] = perfis.get("atual", "")
        except Exception as exc:  # noqa: BLE001
            resultado["avisos"].append(f"não li as lotações do usuário: {exc}")
        if args.perfil:
            painel.perfil = args.perfil.strip().lower()
            if not painel.selecionar_perfil(reabrir_painel=False):
                resultado["avisos"].append("lotação informada não encontrada")
                return 1
        if not painel.abrir_painel():
            resultado["avisos"].append(
                "o painel do usuário interno não abriu neste endereço: este PJe pode ter "
                "outra tela inicial. Use o caminho guiado (reconhecer.py).")
            return 1
        arvore = tp.listar_arvore(painel.frame, "todas")
        resultado["pastas"] = [
            {"id": p["id"], "nome": p["nome"], "quantidade": q}
            for p, q in zip(tp.normalizar_pastas([i["nome"] for i in arvore if i.get("nome")]),
                            [i.get("quantidade") for i in arvore if i.get("nome")])]
        if not resultado["pastas"]:
            resultado["avisos"].append("nenhuma pasta de tarefa visível para esta lotação")
        resultado["ok"] = bool(resultado["pastas"])
        return 0 if resultado["ok"] else 1
    finally:
        try:
            painel.fechar()
        except Exception:  # noqa: BLE001
            pass
        pb.gravar_json_atomico(saida, resultado)
        dizer(f"Sondagem gravada em {saida}")


def _converter(bruto: dict) -> dict:
    pastas = [{"id": p["id"], "nome": p.get("nome") or p["id"], "esperado": p.get("esperado"),
               "avisos": list(p.get("avisos") or [])
               + ([] if p.get("encontrada", True) else ["pasta não encontrada no painel"])}
              for p in bruto.get("pastas", [])]
    itens = []
    for it in bruto.get("itens", []):
        partes = it.get("partes")
        if not partes and (it.get("polo_ativo") or it.get("polo_passivo")):
            partes = f"{it.get('polo_ativo') or '?'} × {it.get('polo_passivo') or '?'}"
        campos = {
            "classe": it.get("classe_sigla"), "assunto": it.get("assunto"),
            "orgao": it.get("orgao"), "partes": partes,
            "etiquetas": it.get("etiquetas") or [], "prioridade": it.get("prioridade"),
            "data_chegada": it.get("data_chegada"), "dias_na_tarefa": it.get("dias_chegada"),
            "ultima_movimentacao": it.get("ultima_movimentacao"),
            "sigilo": it.get("sigiloso"),
        }
        campos = {k: v for k, v in campos.items() if v not in (None, "", [])}
        for pid in [it.get("pasta_id")] + list(it.get("tambem_em") or []):
            itens.append({"identificador": it["numero"], "pasta_id": pid, "campos": campos})
    conf = pb.carregar().get("ferramenta") or {}
    rotulo = " ".join(x for x in ("PJe", conf.get("tribunal"), conf.get("grau")) if x)
    return pb.montar_fila(pastas, itens, ferramenta=rotulo)


def listar(args) -> int:
    saida = Path(args.saida).expanduser() if args.saida else pb.arq_fila()
    with tempfile.TemporaryDirectory(dir=str(pb.dir_dados())) as tmp:
        bruto_arq = Path(tmp) / "bruto.json"
        cmd = [sys.executable, str(AQUI / "listar_tarefas_pje.py"), "--saida", str(bruto_arq),
               "--log", str(pb.dir_dados() / "conector.log")]
        if args.headless:
            cmd.append("--headless")
        codigo = subprocess.call(cmd)
        if not bruto_arq.is_file():
            dizer("ERRO: a listagem não produziu resultado; a fila anterior foi preservada.")
            return codigo or 1
        fila = _converter(json.loads(bruto_arq.read_text(encoding="utf-8")))
    pb.gravar_json_atomico(saida, fila)
    m = fila["manifesto"]
    dizer(f"Fila gravada em {saida}: {m['total_enumerado']} de {m['total_esperado']} esperado(s).")
    return pb.codigo_de_saida(fila)


def baixar(args) -> int:
    destino = Path(args.destino).expanduser() if args.destino else pb.pasta_processos()
    cmd = [sys.executable, str(AQUI / "baixar_painel_pje.py"), *args.identificadores,
           "--destino", str(destino)]
    if args.headless:
        cmd.append("--headless")
    return subprocess.call(cmd)


def main() -> int:
    pb.utf8_no_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sondar")
    s.add_argument("--perfil", default=None)
    s.add_argument("--saida", default=None)
    s.add_argument("--espera-login", type=int, default=900)
    s.add_argument("--headless", action="store_true")
    li = sub.add_parser("listar")
    li.add_argument("--saida", default=None)
    li.add_argument("--headless", action="store_true")
    b = sub.add_parser("baixar")
    b.add_argument("identificadores", nargs="+")
    b.add_argument("--destino", default=None)
    b.add_argument("--headless", action="store_true")
    args = ap.parse_args()
    return {"sondar": sondar, "listar": listar, "baixar": baixar}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
