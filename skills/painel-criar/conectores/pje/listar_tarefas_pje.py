#!/usr/bin/env python3
"""
Lista os processos das pastas de tarefa do Painel do Usuário Interno (PJe).

As pastas acompanhadas são as da configuração da unidade (pje.pastas_tarefa); sem
configuração, todas as que o painel mostrar ao perfil. Grava fila_pje.json em
~/.projurista/dados/, com contagem esperada × enumerada por pasta e manifesto.

Uso:
  python3 listar_tarefas_pje.py [--arvore todas|minhas] [--saida JSON] [--pastas id1,id2]
                                [--perfil NOME] [--headless] [--espera-login 900] [--teto-paginas N]
                                [--log ARQ] [--diagnostico] [--capturas DIR]

Códigos de saída: 0 completo · 1 falha de login/painel (arquivo anterior preservado) · 2 lista parcial.
SOMENTE NAVEGAÇÃO: nenhum processo é aberto, movimentado ou alterado.
"""

import argparse
import json
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pje_painel import PainelPJe  # noqa: E402
import tarefas_pje as tp  # noqa: E402

SAIDA_PADRAO = tp.cfg_unidade.pasta_dados() / "fila_pje.json"
LOG_PADRAO = tp.cfg_unidade.pasta_dados() / "listar_tarefas.log"
# Capturas de diagnóstico contêm dados de processos: ficam na pasta de dados do usuário.
CAPTURAS_PADRAO = tp.cfg_unidade.pasta_dados() / "capturas-tarefas"
TOLERANCIA_CONTADOR = 2

_ARQ_LOG = None


def registrar(msg: str) -> None:
    linha = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(linha, flush=True)
    if _ARQ_LOG:
        try:
            with open(_ARQ_LOG, "a", encoding="utf-8") as fh:
                fh.write(linha + "\n")
        except OSError:
            pass


def gravar_json_atomico(caminho: Path, dados: dict) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".fila-", suffix=".tmp", dir=str(caminho.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(dados, fh, ensure_ascii=False, indent=1)
            fh.write("\n")
        os.replace(tmp, caminho)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _pastas_escolhidas(texto: Optional[str]) -> List[dict]:
    if not texto:
        return list(tp.PASTAS)
    ids = [t.strip() for t in texto.split(",") if t.strip()]
    escolhidas = [p for p in tp.PASTAS if p["id"] in ids]
    desconhecidos = [i for i in ids if i not in {p["id"] for p in tp.PASTAS}]
    if desconhecidos:
        raise SystemExit(f"pastas desconhecidas: {desconhecidos}; use {[p['id'] for p in tp.PASTAS]}")
    return escolhidas


def listar(painel: PainelPJe, arvore: str, pastas: List[dict], teto: Optional[int],
           dir_csv: Path, sem_csv: bool = False) -> List[dict]:
    """Para cada pasta: lê o contador e exporta o CSV; se falhar, abre a pasta e pagina."""
    resultados = []
    dir_csv.mkdir(parents=True, exist_ok=True)
    for i, pasta in enumerate(pastas):
        inicio = time.time()
        registrar(f"Pasta {i + 1}/{len(pastas)}: {pasta['nome']} (árvore {tp.ARVORES[arvore]['rotulo']})")
        res: Dict = {"id": pasta["id"], "nome": pasta["nome"], "sigla": pasta["sigla"], "encontrada": False,
                     "esperado": None, "esperado_cabecalho": None, "enumerados": 0, "paginas_percorridas": 0,
                     "tamanho_pagina": None, "convergiu": False, "completo": False, "motivo_parada": None,
                     "duracao_s": 0, "avisos": [], "itens": [], "rota": None, "arquivo_csv": None}
        if i > 0 and resultados and resultados[-1].get("rota") != "csv" and not painel.abrir_painel():
            res["avisos"].append("painel não reabriu")
            res["motivo_parada"] = "painel não reabriu"
            resultados.append(res)
            continue
        frame = painel.frame
        loc = tp.localizar_pasta(frame, arvore, pasta["nome"])
        if not loc.get("ok"):
            registrar(f"  NÃO ENCONTRADA: {loc.get('motivo')}; candidatos: {loc.get('candidatos', [])[:10]}")
            res["motivo_parada"] = "pasta não encontrada na árvore"
            resultados.append(res)
            continue
        res["encontrada"] = True
        res["esperado"] = loc.get("quantidade")
        registrar(f"  contador da árvore: {res['esperado']} (via {loc.get('via')})")
        # Rota principal: exportação CSV pelo ícone da árvore (sem abrir a pasta).
        if not sem_csv:
            exp = tp.exportar_csv(painel, frame, arvore, pasta["nome"], dir_csv, registrar)
            if exp.get("ok"):
                itens = exp["itens"]
                res.update({"itens": itens, "enumerados": len(itens), "paginas_percorridas": 0, "tamanho_pagina": None,
                            "rota": "csv", "arquivo_csv": exp.get("arquivo")})
                # O contador da árvore é lido no carregamento do painel e pode atrasar em relação ao CSV
                # (processo movido entre uma leitura e outra). O CSV é a fonte fiel: tolera-se divergência de até 2.
                diverg = abs(len(itens) - res["esperado"]) if res["esperado"] is not None else 0
                res["divergencia"] = diverg
                res["convergiu"] = res["esperado"] is None or diverg <= TOLERANCIA_CONTADOR
                res["motivo_parada"] = "exportação CSV"
                if diverg:
                    res["avisos"].append(f"CSV com {len(itens)} linhas para contador {res['esperado']} "
                                         f"(divergência de {diverg}; provável movimentação entre as leituras)")
                res["completo"] = bool(res["convergiu"] and res["esperado"] is not None)
                res["duracao_s"] = round(time.time() - inicio, 1)
                registrar(f"  resultado: {res['enumerados']}/{res['esperado']} via CSV, completo={res['completo']}, {res['duracao_s']}s")
                resultados.append(res)
                continue
            registrar(f"  exportação CSV indisponível ({exp.get('motivo')}); usando a paginação")
            res["avisos"].append("CSV indisponível; enumerado por paginação")
            if not painel.abrir_painel():
                res["motivo_parada"] = "painel não reabriu"
                resultados.append(res)
                continue
            frame = painel.frame
        res["rota"] = "paginacao"
        ab = tp.abrir_pasta(frame, arvore, pasta["nome"], registrar)
        if not ab.get("ok"):
            res["motivo_parada"] = f"não abriu: {ab.get('motivo')}"
            resultados.append(res)
            continue
        frame = painel.frame
        lst = tp.esperar_lista(frame, pasta["nome"], espera=30, log=registrar)
        res["esperado_cabecalho"] = lst.get("esperado_cabecalho")
        if not lst.get("ok"):
            res["avisos"].append("lista não confirmada (cabeçalho ou processos ausentes)")
        if lst.get("vazio") and not lst.get("n_cnj"):
            registrar("  pasta vazia")
            res.update({"convergiu": True, "completo": (res["esperado"] in (0, None)), "motivo_parada": "pasta vazia"})
            if res["esperado"]:
                res["avisos"].append(f"árvore indica {res['esperado']} mas a lista veio vazia")
            res["duracao_s"] = round(time.time() - inicio, 1)
            resultados.append(res)
            continue
        en = tp.enumerar_pasta(frame, pasta, res["esperado"], registrar, teto)
        res.update({k: en[k] for k in ("itens", "enumerados", "paginas_percorridas", "tamanho_pagina", "convergiu", "motivo_parada")})
        res["avisos"].extend(en["avisos"])
        res["completo"] = bool(res["encontrada"] and res["convergiu"] and res["esperado"] is not None
                               and res["enumerados"] == res["esperado"])
        res["duracao_s"] = round(time.time() - inicio, 1)
        registrar(f"  resultado: {res['enumerados']}/{res['esperado']} em {res['paginas_percorridas']} página(s), "
                  f"completo={res['completo']} ({res['motivo_parada']}), {res['duracao_s']}s")
        resultados.append(res)
    return resultados


def consolidar(resultados: List[dict], arvore: str, perfil: Optional[str], inicio: float, log_path: Path) -> dict:
    ordem = {p["id"]: i for i, p in enumerate(tp.PASTAS)}
    itens: Dict[str, dict] = {}
    duplicados = set()
    for res in sorted(resultados, key=lambda r: ordem[r["id"]]):
        for c in res.pop("itens", []):
            item = {
                "numero": c["numero"], "pasta_id": res["id"], "pasta_pje": res["nome"],
                "classe_sigla": c.get("classe_sigla"), "assunto": c.get("assunto"), "orgao": c.get("orgao"),
                "partes": c.get("partes"), "ultima_movimentacao": c.get("ultima_movimentacao"),
                "etiquetas": c.get("etiquetas") or [], "prioridade": c.get("prioridade"),
                "pagina": c.get("pagina"), "posicao": c.get("posicao"), "tambem_em": [],
                # Campos extras do CSV (ausentes na rota de paginação): sempre presentes, null quando não lidos.
                "polo_ativo": c.get("polo_ativo"), "polo_passivo": c.get("polo_passivo"),
                "ultimo_movimento_em": c.get("ultimo_movimento_em"), "dias_ultimo_movimento": c.get("dias_ultimo_movimento"),
                "data_chegada": c.get("data_chegada"), "dias_chegada": c.get("dias_chegada"),
                "conferido": c.get("conferido"), "sigiloso": c.get("sigiloso"), "nivel_acesso": c.get("nivel_acesso"),
            }
            if c["numero"] in itens:
                itens[c["numero"]]["tambem_em"].append(res["id"])
                duplicados.add(c["numero"])
            else:
                itens[c["numero"]] = item
    pastas = [{k: v for k, v in r.items()} for r in resultados]
    incompletas = [p["id"] for p in pastas if not p["completo"]]
    nao_encontradas = [p["id"] for p in pastas if not p["encontrada"]]
    completo = not incompletas
    return {
        "versao": 1, "app": "listar_tarefas_pje", "gerada_em": datetime.now().isoformat(timespec="seconds"),
        "duracao_s": round(time.time() - inicio, 1), "arvore": arvore, "perfil": perfil,
        "pastas": pastas, "itens": list(itens.values()),
        "manifesto": {
            "completo": completo,
            "total_esperado": sum(p["esperado"] or 0 for p in pastas),
            "total_enumerado": sum(p["enumerados"] for p in pastas),
            "total_unicos": len(itens),
            "duplicados_entre_pastas": sorted(duplicados),
            "pastas_incompletas": incompletas, "pastas_nao_encontradas": nao_encontradas,
            "codigo_saida": 0 if completo else 2, "log": str(log_path),
        },
    }


def resumo_terminal(dados: dict) -> str:
    linhas = [f"{'PASTA':<14} {'ESPERADO':>8} {'ENUMERADOS':>10} {'COMPLETO':>8} {'PÁGINAS':>7} {'TEMPO':>7}  MOTIVO"]
    linhas.append("-" * 80)
    for p in dados["pastas"]:
        linhas.append(f"{p['sigla']:<14} {str(p['esperado'] if p['esperado'] is not None else '?'):>8} {p['enumerados']:>10} "
                      f"{'sim' if p['completo'] else 'NÃO':>8} {p['paginas_percorridas']:>7} {str(p['duracao_s']) + 's':>7}  {p['motivo_parada'] or ''}")
    m = dados["manifesto"]
    linhas.append("")
    linhas.append(f"árvore {dados['arvore']} · {m['total_unicos']} processo(s) único(s) de {m['total_esperado']} esperado(s)"
                  f" · duplicados entre pastas: {len(m['duplicados_entre_pastas'])} · completo: {'sim' if m['completo'] else 'NÃO'}"
                  f" · {dados['duracao_s']}s")
    for p in dados["pastas"]:
        for a in p["avisos"]:
            linhas.append(f"aviso ({p['sigla']}): {a}")
    return "\n".join(linhas)


def diagnostico(painel: PainelPJe, arvore: str, pastas: List[dict], destino: Path) -> int:
    carimbo = datetime.now().strftime("%Y%m%d-%H%M")
    destino = destino / carimbo
    destino.mkdir(parents=True, exist_ok=True)
    registrar(f"Diagnóstico em {destino}")
    frame = painel.frame
    tp._salvar_captura(painel, frame, destino, "00_painel", registrar)
    saida: Dict = {"carimbo": carimbo, "arvore": arvore, "arvores": {}, "pastas": []}
    for nome_arv in ("todas", "minhas"):
        lista = tp.listar_arvore(frame, nome_arv)
        saida["arvores"][nome_arv] = lista
        registrar(f"árvore {nome_arv}: {len(lista)} pasta(s)")
        for item in lista:
            marca = " <==" if any(item["nome"] == p["nome"] for p in tp.PASTAS) else ""
            registrar(f"   {item['quantidade']!s:>5}  {item['nome']}{marca}")
    for i, pasta in enumerate(pastas, start=1):
        if i > 1:
            painel.abrir_painel()
        registrar(f"--- {pasta['nome']} ---")
        d = tp.diagnosticar_pasta(painel, arvore, pasta, destino, i, registrar)
        saida["pastas"].append(d)
    # Exportação pela árvore (só diagnóstico): volta ao painel e tenta o ícone da primeira pasta.
    painel.abrir_painel()
    saida["exportacao"] = tp.exportar_csv(painel, painel.frame, arvore, pastas[0]["nome"], destino, registrar)
    if saida["exportacao"].get("ok"):
        saida["exportacao"]["n_itens"] = len(saida["exportacao"].pop("itens", []))
    (destino / "99_diagnostico.json").write_text(json.dumps(saida, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    registrar(f"Diagnóstico gravado em {destino / '99_diagnostico.json'}")
    return 0


def main() -> int:
    global _ARQ_LOG
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--arvore", choices=list(tp.ARVORES), default="todas")
    ap.add_argument("--saida", default=str(SAIDA_PADRAO))
    ap.add_argument("--pastas", default=None, help="ids das pastas, separados por vírgula (veja os ids com: unidade.py json)")
    ap.add_argument("--perfil", default=None)
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--espera-login", type=int, default=900)
    ap.add_argument("--teto-paginas", type=int, default=None)
    ap.add_argument("--sem-csv", action="store_true", help="ignora a exportação CSV e enumera pela paginação")
    ap.add_argument("--log", default=str(LOG_PADRAO))
    ap.add_argument("--diagnostico", action="store_true", help="só captura DOM/PNG e imprime candidatos de seletores")
    ap.add_argument("--capturas", default=str(CAPTURAS_PADRAO))
    args = ap.parse_args()
    tp.cfg_unidade.utf8_no_console()
    tp.cfg_unidade.garantir_ambiente("playwright")

    _ARQ_LOG = Path(args.log).expanduser()
    _ARQ_LOG.parent.mkdir(parents=True, exist_ok=True)
    registrar(f"=== execução {datetime.now().isoformat(timespec='seconds')} árvore={args.arvore} ===")
    inicio = time.time()

    painel = PainelPJe(headless=args.headless, perfil=args.perfil, log=registrar)
    try:
        painel.iniciar()
        if not painel.login(espera_2fa=args.espera_login):
            registrar("ERRO: login falhou. Se usou --headless, execute sem ele para concluir o segundo fator.")
            return 1
        if not painel.selecionar_perfil(reabrir_painel=False):
            return 1
        if not painel.abrir_painel():
            registrar("ERRO: painel não abriu.")
            return 1
        if not tp.PASTAS:
            tp.PASTAS.extend(tp.pastas_da_arvore(painel.frame, args.arvore))
            registrar(f"Pastas de tarefa não configuradas: usando as {len(tp.PASTAS)} que o painel mostra. "
                      "Para escolher quais acompanhar, rode /painel-criar.")
        if not tp.PASTAS:
            registrar("ERRO: o painel não mostrou nenhuma pasta de tarefa para este perfil.")
            return 1
        pastas = _pastas_escolhidas(args.pastas)
        if args.diagnostico:
            return diagnostico(painel, args.arvore, pastas, Path(args.capturas).expanduser())
        resultados = listar(painel, args.arvore, pastas, args.teto_paginas,
                            Path(args.saida).expanduser().parent / "csv_pje", args.sem_csv)
        dados = consolidar(resultados, args.arvore, getattr(painel, "perfil", None), inicio, _ARQ_LOG)
        gravar_json_atomico(Path(args.saida).expanduser(), dados)
        registrar(f"Gravado {args.saida}")
        print(resumo_terminal(dados))
        return dados["manifesto"]["codigo_saida"]
    except KeyboardInterrupt:
        registrar("Interrompido pelo usuário.")
        return 1
    finally:
        try:
            painel.fechar()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    sys.exit(main())
