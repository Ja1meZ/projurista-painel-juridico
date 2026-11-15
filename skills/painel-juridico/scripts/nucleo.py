#!/usr/bin/env python3
"""
Núcleo do Painel Jurídico: lê a pasta dos processos e a fila da ferramenta, infere a
fase de cada processo e registra anotações e pedidos de rascunho.

A fase de um processo sai do que existe na pasta dele:

    <pasta dos processos>/<identificador>[ - sufixo]/
        minutas/<arquivo da peça>      peças prontas (nomes definidos na configuração)
        _painel.json                   anotações, conferência e pedidos (só este módulo escreve)
        _manifesto_download.json       opcional: prova de download completo

Linha de comando (usada pelo Claude Code):

    python nucleo.py resumo
    python nucleo.py estado [--json]
    python nucleo.py pedidos [--json] [--status pendente|em_andamento|todos]
    python nucleo.py anotar --pasta P [--pendencia T | --limpar-pendencia]
                            [--conferida sim|nao] [--tag T ...] [--obs T]
                            [--pedido-id ID --pedido-status S]
    python nucleo.py pedir --pasta P --peca ID [--orientacao T]
"""
import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import painel_base as pb  # noqa: E402

ARQ_PAINEL = "_painel.json"
ARQ_MANIFESTO = "_manifesto_download.json"
STATUS_PEDIDO = ("pendente", "em_andamento", "concluido", "cancelado")
MAX_PEDIDOS = 30


def agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ------------------------------------------------------------------ _painel.json

def painel_vazio() -> dict:
    return {"versao": 1, "atualizado_em": None, "atualizado_por": None, "pendencia": "",
            "conferida": {"valor": False, "em": None}, "tags": [], "observacoes": "",
            "pedidos": []}


def ler_painel(pasta: Path) -> dict:
    dados = painel_vazio()
    arq = pasta / ARQ_PAINEL
    if arq.is_file():
        try:
            lido = json.loads(arq.read_text(encoding="utf-8"))
            if isinstance(lido, dict):
                dados.update(lido)
        except (OSError, ValueError):
            dados["_ilegivel"] = True
    if not isinstance(dados.get("conferida"), dict):
        dados["conferida"] = {"valor": bool(dados.get("conferida")), "em": None}
    if not isinstance(dados.get("pedidos"), list):
        dados["pedidos"] = []
    if not isinstance(dados.get("tags"), list):
        dados["tags"] = []
    return dados


def _gravar_painel(pasta: Path, dados: dict, por: str) -> dict:
    dados.pop("_ilegivel", None)
    dados["atualizado_em"] = agora()
    dados["atualizado_por"] = por
    dados["pedidos"] = dados["pedidos"][-MAX_PEDIDOS:]
    pb.gravar_json_atomico(pasta / ARQ_PAINEL, dados, restrito=False)
    return dados


def anotar(pasta: Path, pendencia: Optional[str] = None, conferida: Optional[bool] = None,
           tags: Optional[List[str]] = None, observacoes: Optional[str] = None,
           por: str = "painel") -> dict:
    """Altera só os campos informados (None = não mexe)."""
    dados = ler_painel(pasta)
    if pendencia is not None:
        dados["pendencia"] = pendencia.strip()
    if conferida is not None:
        dados["conferida"] = {"valor": bool(conferida), "em": agora() if conferida else None}
    if tags is not None:
        vistos, limpas = set(), []
        for t in tags:
            t = str(t).strip()
            if t and t.lower() not in vistos:
                vistos.add(t.lower())
                limpas.append(t[:40])
        dados["tags"] = limpas[:20]
    if observacoes is not None:
        dados["observacoes"] = observacoes.strip()[:4000]
    return _gravar_painel(pasta, dados, por)


def novo_pedido(pasta: Path, peca_id: str, orientacao: str = "", por: str = "painel",
                conf: Optional[dict] = None) -> dict:
    conf = conf or pb.carregar()
    catalogo = {p["id"]: p for p in pb.pecas(conf)}
    if peca_id not in catalogo:
        raise ValueError(f"Peça desconhecida: {peca_id}. Opções: {', '.join(catalogo) or '(nenhuma)'}")
    dados = ler_painel(pasta)
    for p in dados["pedidos"]:
        if p.get("peca") == peca_id and p.get("status") in ("pendente", "em_andamento"):
            raise ValueError(f"Já existe pedido aberto de {catalogo[peca_id]['nome']} neste processo.")
    pedido = {"id": uuid.uuid4().hex[:8], "peca": peca_id, "orientacao": orientacao.strip()[:4000],
              "status": "pendente", "criado_em": agora(), "atualizado_em": agora()}
    dados["pedidos"].append(pedido)
    _gravar_painel(pasta, dados, por)
    return pedido


def mudar_pedido(pasta: Path, pedido_id: str, status: str, por: str = "painel") -> dict:
    if status not in STATUS_PEDIDO:
        raise ValueError(f"Status inválido: {status}")
    dados = ler_painel(pasta)
    for p in dados["pedidos"]:
        if p.get("id") == pedido_id:
            p["status"] = status
            p["atualizado_em"] = agora()
            _gravar_painel(pasta, dados, por)
            return p
    raise ValueError(f"Pedido {pedido_id} não encontrado em {pasta.name}")


# --------------------------------------------------------------------- varredura

def identificador_da_pasta(nome: str, regex) -> Optional[str]:
    m = regex.match(nome)
    if not m:
        return None
    resto = nome[m.end():]
    if resto and not resto.startswith((" ", "-", "_")):
        return None
    return m.group(0)


def listar_pastas(raiz: Path, regex) -> List[Path]:
    if not raiz.is_dir():
        return []
    saida = []
    for p in sorted(raiz.iterdir()):
        if p.is_dir() and not p.name.startswith((".", "_")) and identificador_da_pasta(p.name, regex):
            saida.append(p)
    return saida


def _manifesto(pasta: Path) -> Optional[dict]:
    arq = pasta / ARQ_MANIFESTO
    if not arq.is_file():
        return None
    try:
        m = json.loads(arq.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"ilegivel": True}
    return {"completo": m.get("completo"), "esperado": m.get("esperado"),
            "baixado": m.get("baixado"), "erro": m.get("erro_fatal"),
            "classe": m.get("classe_judicial"), "assunto": m.get("assunto")}


def _contar_autos(pasta: Path, teto: int = 5000) -> int:
    n = 0
    for raiz, dirs, arquivos in os.walk(pasta):
        dirs[:] = [d for d in dirs if d != "minutas" and not d.startswith(".")]
        n += sum(1 for a in arquivos if not a.startswith(("_", ".")))
        if n >= teto:
            break
    return n


def inferir_processo(pasta: Path, conf: dict, regex=None) -> dict:
    regex = regex or pb.regex_identificador(conf)
    fases = pb.fases(conf)
    ordem = {f["id"]: i for i, f in enumerate(fases)}
    catalogo = pb.pecas(conf)
    painel = ler_painel(pasta)
    dir_min = pasta / "minutas"
    arquivos = sorted(a.name for a in dir_min.iterdir() if a.is_file() and not a.name.startswith(".")) \
        if dir_min.is_dir() else []
    presentes, conhecidos = [], set()
    for p in catalogo:
        if p["arquivo"] in arquivos:
            presentes.append(p["id"])
            conhecidos.add(p["arquivo"])
    fora = [a for a in arquivos if a not in conhecidos]

    if painel["conferida"].get("valor"):
        fase = fases[-1]["id"]
    elif presentes:
        fase = max((p["fase"] for p in catalogo if p["id"] in presentes), key=lambda f: ordem[f])
        if fase == fases[-1]["id"]:      # a última fase só se alcança conferindo
            fase = fases[-2]["id"]
    else:
        fase = fases[0]["id"]

    manifesto = _manifesto(pasta)
    n_autos = _contar_autos(pasta)
    alertas = []
    if painel.get("_ilegivel"):
        alertas.append("arquivo de anotações ilegível")
    if manifesto and manifesto.get("completo") is False:
        alertas.append("download incompleto")
    if manifesto and manifesto.get("erro"):
        alertas.append("download com erro")
    if n_autos == 0:
        alertas.append("pasta sem arquivos do processo")

    try:
        ultima = max((a.stat().st_mtime for a in [pasta, dir_min, pasta / ARQ_PAINEL] if a.exists()),
                     default=0)
    except OSError:
        ultima = 0
    abertos = [p for p in painel["pedidos"] if p.get("status") in ("pendente", "em_andamento")]
    return {
        "identificador": identificador_da_pasta(pasta.name, regex) or pasta.name,
        "pasta": pasta.name, "caminho": str(pasta), "fase": fase,
        "pecas": presentes, "minutas_fora_do_padrao": fora, "n_arquivos": n_autos,
        "manifesto": manifesto, "alertas": alertas,
        "pendencia": painel.get("pendencia") or "", "tags": painel.get("tags") or [],
        "observacoes": painel.get("observacoes") or "",
        "conferida": bool(painel["conferida"].get("valor")),
        "pedidos": painel["pedidos"][-8:], "pedidos_abertos": len(abertos),
        "ultima_atividade": int(ultima), "campos": {}, "pastas_tarefa": [],
    }


def ler_fila(arq: Optional[Path] = None) -> dict:
    arq = arq or pb.arq_fila()
    vazio = {"existe": False, "pastas": [], "itens": [], "manifesto": {}, "gerada_em": None,
             "idade_s": None, "erros": []}
    if not arq.is_file():
        return vazio
    try:
        fila = json.loads(arq.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        vazio["erros"] = [f"fila ilegível: {exc}"]
        return vazio
    erros = pb.validar_fila(fila)
    if erros:
        vazio["erros"] = erros[:5]
        return vazio
    fila["existe"] = True
    fila["erros"] = []
    try:
        fila["idade_s"] = int(time.time() - arq.stat().st_mtime)
    except OSError:
        fila["idade_s"] = None
    return fila


def varrer(conf: Optional[dict] = None, arq_fila: Optional[Path] = None) -> dict:
    conf = conf or pb.carregar()
    regex = pb.regex_identificador(conf)
    raiz = pb.pasta_processos(conf)
    processos = [inferir_processo(p, conf, regex) for p in listar_pastas(raiz, regex)]
    por_id = {}
    for p in processos:
        por_id.setdefault(p["identificador"], p)

    fila = ler_fila(arq_fila)
    agrupados = {}
    for it in fila.get("itens", []):
        ident = it["identificador"]
        g = agrupados.setdefault(ident, {"identificador": ident, "pastas_tarefa": [], "campos": {}})
        if it["pasta_id"] not in g["pastas_tarefa"]:
            g["pastas_tarefa"].append(it["pasta_id"])
        for k, v in (it.get("campos") or {}).items():
            g["campos"].setdefault(k, v)
    itens_fila = []
    for ident, g in agrupados.items():
        local = por_id.get(ident)
        if local:
            local["campos"] = g["campos"]
            local["pastas_tarefa"] = g["pastas_tarefa"]
        g["ja_baixado"] = bool(local)
        g["pasta_local"] = local["pasta"] if local else None
        itens_fila.append(g)

    ferramenta = conf.get("ferramenta") or {}
    conector = pb.caminho_conector(conf)
    return {
        "app": "painel-juridico", "gerado_em": agora(),
        "config": {
            "titulo": " ".join(x for x in (ferramenta.get("sistema"), ferramenta.get("tribunal"),
                                           ferramenta.get("grau")) if x) or "Painel Jurídico",
            "raiz": str(raiz), "raiz_existe": raiz.is_dir(),
            "rotulo_identificador": (conf.get("identificador") or {}).get("rotulo") or "Número",
            "fases": pb.fases(conf), "pecas": pb.pecas(conf),
            "campos_cartao": conf.get("campos_cartao") or [],
            "pastas_tarefa": [{"id": p["id"], "nome": p["nome"]} for p in fila.get("pastas", [])]
            or pb.normalizar_lista(conf.get("pastas_tarefa")),
            "conector": bool(conector and conector.is_file()),
            "pode_baixar": bool((conf.get("conector") or {}).get("baixar")),
            "faltando": pb.faltando(conf),
        },
        "processos": processos,
        "fila": {"existe": fila["existe"], "gerada_em": fila.get("gerada_em"),
                 "idade_s": fila.get("idade_s"), "pastas": fila.get("pastas", []),
                 "manifesto": fila.get("manifesto", {}), "erros": fila.get("erros", []),
                 "itens": itens_fila},
    }


# ----------------------------------------------------------------------- pedidos

def _fontes(lista) -> str:
    linhas = []
    for f in lista or []:
        if isinstance(f, str):
            linhas.append(f"  - {f}")
        elif isinstance(f, dict):
            partes = [str(f[k]) for k in ("tipo", "onde") if f.get(k)]
            linha = "  - " + " — ".join(partes)
            if f.get("como"):
                linha += f" (como consultar: {f['como']})"
            linhas.append(linha)
    return "\n".join(linhas)


def instrucao(processo: dict, pedido: dict, conf: dict) -> str:
    """Texto que o Claude Code segue para cumprir um pedido de rascunho."""
    catalogo = {p["id"]: p for p in pb.pecas(conf)}
    peca = catalogo.get(pedido["peca"], {"nome": pedido["peca"], "arquivo": f"{pedido['peca']}.txt"})
    ref = conf.get("referencias") or {}
    ferr = conf.get("ferramenta") or {}
    blocos = [
        f"Processo {processo['identificador']} — pasta: {processo['caminho']}",
        f"Peça pedida: {peca['nome']}. Grave em: minutas/{peca['arquivo']} (dentro da pasta do processo).",
    ]
    if ferr.get("tribunal") or ferr.get("grau"):
        blocos.append(f"Contexto de trabalho do usuário: {ferr.get('tribunal') or ''} {ferr.get('grau') or ''}".strip())
    if processo.get("campos"):
        blocos.append("Dados da fila: " + "; ".join(f"{k}: {v}" for k, v in processo["campos"].items()
                                                     if not isinstance(v, (list, dict))))
    if pedido.get("orientacao"):
        blocos.append(f"Orientação do usuário para esta peça:\n{pedido['orientacao']}")
    if processo.get("observacoes"):
        blocos.append(f"Observações do cartão:\n{processo['observacoes']}")
    if processo.get("pendencia"):
        blocos.append(f"Pendência registrada (considere antes de redigir): {processo['pendencia']}")
    if processo.get("pecas"):
        prontas = ", ".join(catalogo[i]["arquivo"] for i in processo["pecas"] if i in catalogo)
        blocos.append(f"Peças já existentes em minutas/ (leia antes; não sobrescreva sem motivo): {prontas}")
    if ref.get("modelos"):
        blocos.append("Modelos do usuário (siga a estrutura e o estilo deles):\n" + _fontes(ref["modelos"]))
    if ref.get("precedentes"):
        blocos.append("Onde pesquisar precedentes e legislação:\n" + _fontes(ref["precedentes"]))
    if ref.get("mcps"):
        blocos.append("Conexões (MCP) que o usuário declarou ter: " + ", ".join(ref["mcps"])
                      + ". Use só as que estiverem de fato disponíveis nesta sessão.")
    if ref.get("observacoes"):
        blocos.append(f"Preferências de redação do usuário:\n{ref['observacoes']}")
    blocos.append(
        "Regras fixas: leia os autos na pasta antes de escrever; não invente fatos; só cite lei, "
        "súmula ou precedente que você tenha lido nas fontes acima, que esteja nos autos ou que o "
        "usuário tenha fornecido — fora disso, diga que não localizou em vez de citar de memória; "
        "o sentido da decisão é do usuário: se a orientação não o indicar, exponha as alternativas "
        "no início da resposta (fora da peça) e sinalize o que escolheu sozinho; o resultado é um "
        "rascunho para conferência humana.")
    return "\n\n".join(blocos)


def listar_pedidos(status: str = "pendente", conf: Optional[dict] = None) -> List[dict]:
    conf = conf or pb.carregar()
    estado = varrer(conf)
    catalogo = {p["id"]: p for p in pb.pecas(conf)}
    saida = []
    for proc in estado["processos"]:
        for ped in proc["pedidos"]:
            if status != "todos" and ped.get("status") != status:
                continue
            peca = catalogo.get(ped["peca"], {})
            saida.append({
                "identificador": proc["identificador"], "pasta": proc["caminho"],
                "pedido_id": ped["id"], "status": ped["status"], "peca": ped["peca"],
                "peca_nome": peca.get("nome") or ped["peca"],
                "saida": f"minutas/{peca.get('arquivo') or ped['peca'] + '.txt'}",
                "criado_em": ped.get("criado_em"), "alertas": proc["alertas"],
                "instrucao": instrucao(proc, ped, conf),
            })
    saida.sort(key=lambda x: x.get("criado_em") or "")
    return saida


# --------------------------------------------------------------------------- CLI

def resolver_pasta(texto: str, conf: Optional[dict] = None) -> Path:
    """Aceita caminho, nome de pasta ou identificador; exige pasta filha da raiz."""
    conf = conf or pb.carregar()
    raiz = pb.pasta_processos(conf).resolve()
    regex = pb.regex_identificador(conf)
    candidato = Path(texto).expanduser()
    if not candidato.is_absolute():
        candidato = raiz / texto
    candidato = candidato.resolve()
    if candidato.is_dir() and candidato.parent == raiz and identificador_da_pasta(candidato.name, regex):
        return candidato
    for p in listar_pastas(raiz, regex):
        if identificador_da_pasta(p.name, regex) == texto.strip():
            return p
    raise FileNotFoundError(f"Pasta de processo não encontrada dentro de {raiz}: {texto}")


def texto_resumo(estado: dict) -> str:
    cfg = estado["config"]
    linhas = [f"{cfg['titulo']} — pasta dos processos: {cfg['raiz']}"]
    if cfg["faltando"]:
        linhas.append("Falta configurar: " + ", ".join(cfg["faltando"]) + " (rode /painel-criar)")
    fila = estado["fila"]
    if fila["existe"]:
        m = fila["manifesto"]
        linhas.append(f"Fila (lida em {fila['gerada_em']}): {len(fila['itens'])} processo(s)"
                      + ("" if m.get("completo") else " — LEITURA PARCIAL"))
        for p in fila["pastas"]:
            linhas.append(f"  {p['nome']}: {p['enumerados']}"
                          + (f" de {p['esperado']}" if p.get("esperado") is not None else ""))
    else:
        linhas.append("Fila ainda não lida" + (": " + "; ".join(fila["erros"]) if fila["erros"] else "."))
    for f in cfg["fases"]:
        grupo = [p for p in estado["processos"] if p["fase"] == f["id"]]
        linhas.append(f"{f['nome']}: {len(grupo)}")
        for p in grupo[:40]:
            extras = []
            if p["pendencia"]:
                extras.append(f"pendência: {p['pendencia']}")
            if p["pedidos_abertos"]:
                extras.append(f"{p['pedidos_abertos']} pedido(s) aberto(s)")
            extras += p["alertas"]
            linhas.append(f"  {p['identificador']}" + (" — " + "; ".join(extras) if extras else ""))
    return "\n".join(linhas)


def main() -> int:
    pb.utf8_no_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("resumo")
    e = sub.add_parser("estado")
    e.add_argument("--json", action="store_true")
    pe = sub.add_parser("pedidos")
    pe.add_argument("--json", action="store_true")
    pe.add_argument("--status", default="pendente", choices=STATUS_PEDIDO + ("todos",))
    an = sub.add_parser("anotar")
    an.add_argument("--pasta", required=True)
    an.add_argument("--pendencia")
    an.add_argument("--limpar-pendencia", action="store_true")
    an.add_argument("--conferida", choices=("sim", "nao"))
    an.add_argument("--tag", action="append")
    an.add_argument("--obs")
    an.add_argument("--pedido-id")
    an.add_argument("--pedido-status", choices=STATUS_PEDIDO)
    an.add_argument("--por", default="claude")
    pd = sub.add_parser("pedir")
    pd.add_argument("--pasta", required=True)
    pd.add_argument("--peca", required=True)
    pd.add_argument("--orientacao", default="")
    args = ap.parse_args()

    try:
        if args.cmd in (None, "resumo"):
            print(texto_resumo(varrer()))
        elif args.cmd == "estado":
            est = varrer()
            print(json.dumps(est, ensure_ascii=False, indent=2) if args.json else texto_resumo(est))
        elif args.cmd == "pedidos":
            lista = listar_pedidos(args.status)
            if args.json:
                print(json.dumps(lista, ensure_ascii=False, indent=2))
            elif not lista:
                print("Nenhum pedido com esse status.")
            else:
                for p in lista:
                    print(f"[{p['status']}] {p['identificador']} — {p['peca_nome']} → {p['saida']} "
                          f"(pedido {p['pedido_id']})")
        elif args.cmd == "anotar":
            pasta = resolver_pasta(args.pasta)
            if args.pedido_status:
                if not args.pedido_id:
                    raise ValueError("--pedido-status exige --pedido-id")
                mudar_pedido(pasta, args.pedido_id, args.pedido_status, por=args.por)
            pend = "" if args.limpar_pendencia else args.pendencia
            conf_v = None if args.conferida is None else args.conferida == "sim"
            if pend is not None or conf_v is not None or args.tag is not None or args.obs is not None:
                tags = None
                if args.tag is not None:
                    tags = ler_painel(pasta)["tags"] + args.tag
                anotar(pasta, pendencia=pend, conferida=conf_v, tags=tags, observacoes=args.obs,
                       por=args.por)
            print(f"Registrado em {pasta.name}.")
        elif args.cmd == "pedir":
            ped = novo_pedido(resolver_pasta(args.pasta), args.peca, args.orientacao, por="claude")
            print(f"Pedido {ped['id']} criado.")
    except (ValueError, FileNotFoundError) as exc:
        print(f"ERRO: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
