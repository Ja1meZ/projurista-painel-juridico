#!/usr/bin/env python3
"""
Download íntegro de processos do PJe via Painel do Usuário Interno.

Diferenca essencial em relacao aos scripts antigos: a timeline e carregada ate
convergir, e a completude e conferida contra o proprio PJe e registrada em
`_manifesto_download.json`. O processo nunca e declarado completo sem prova.

Uso:
    python3 baixar_painel_pje.py 0000000-00.0000.0.00.0000
    python3 baixar_painel_pje.py NUM1 NUM2 --destino ~/outra-pasta
    python3 baixar_painel_pje.py lista.txt --rota autos

Codigos de saida: 0 completo | 1 erro | 2 baixou parcial
"""

import argparse
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import manifesto as mf          # noqa: E402
import materia                  # noqa: E402
import timeline as tl           # noqa: E402
from pje_painel import PainelPJe, HOST_PJE, cfg_unidade  # noqa: E402

PADRAO_CNJ = re.compile(r"^\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}$")


def registrar(mensagem: str):
    print(f"[{time.strftime('%H:%M:%S')}] {mensagem}", flush=True)


def resolver_processos(entradas: list) -> list:
    """Aceita numeros CNJ soltos ou um arquivo com um por linha."""
    numeros = []
    for entrada in entradas:
        caminho = Path(entrada).expanduser()
        if caminho.exists() and caminho.is_file():
            for linha in caminho.read_text(encoding="utf-8").splitlines():
                linha = linha.strip()
                if linha and not linha.startswith("#"):
                    numeros.append(linha)
        else:
            numeros.append(entrada.strip())

    validos, invalidos = [], []
    for n in numeros:
        (validos if PADRAO_CNJ.match(n) else invalidos).append(n)
    for n in invalidos:
        registrar(f"AVISO: número fora do padrão CNJ, ignorado: {n}")
    return validos


def nome_da_pasta(numero: str, documentos: list) -> str:
    """Sufixo pela classe recursal, quando dedutível dos nomes das peças."""
    sufixo = ""
    for doc in documentos:
        nome = (doc.get("nome") or "").lower()
        if "agravo de instrumento" in nome:
            sufixo = " - Agravo de Instrumento"
            break
        if nome.startswith("apelação") or nome.startswith("apelacao"):
            sufixo = " - Recurso de Apelação"
            break
    return tl.limpar_nome_arquivo(numero, 80) + sufixo


def baixar_pela_timeline(painel, numero: str, destino: Path) -> mf.Manifesto:
    pagina = painel.popup
    # Interface ng2 (Angular): o conteudo dos autos fica no iframe `ngFrame`,
    # e a enumeracao, os metadados e o oraculo de completude sao outros.
    ng2 = bool(getattr(painel, "interface_ng2", False))
    frame = getattr(painel, "frame_autos", None) if ng2 else None
    id_proc = painel.id_processo()
    registrar(f"Identificador interno do processo: {id_proc or 'não localizado'}")
    if not tl.SEGMENTO:
        # Alguns tribunais exigem "SIGLA/grau" no endereço de download; a própria
        # página dos autos costuma trazer um link com esse trecho.
        try:
            achado = re.search(r"documento/download/([A-Za-z0-9]+/\w+)/\d+/", pagina.content())
            if achado:
                tl.SEGMENTO = achado.group(1)
                registrar(f"Segmento de download detectado: {tl.SEGMENTO}")
        except Exception:
            pass

    if ng2:
        metadados = materia.ler_metadados_ng2(frame)
    else:
        metadados = materia.ler_metadados(pagina)
    deteccao = materia.detectar(metadados)
    if deteccao.get("classe"):
        registrar(f"Classe judicial: {deteccao['classe']}")
    if deteccao.get("assunto"):
        registrar(f"Assunto: {deteccao['assunto']}")
    registrar(f"Perfil de estruturação: {deteccao.get('perfil') or 'indeterminado'} "
              f"(confiança {deteccao['confianca']} — {deteccao['motivo']})")

    if ng2:
        pag = tl.carregar_documentos_ng2(frame, log=registrar)
        documentos, duplicatas = tl.enumerar_documentos_ng2(frame, log=registrar)
    else:
        pag = tl.carregar_timeline_completa(pagina, log=registrar)
        documentos, duplicatas = tl.enumerar_documentos(pagina, log=registrar)

    if not deteccao.get("perfil"):
        # Sem classe nem assunto, os nomes das pecas sao o ultimo recurso.
        deteccao = materia.detectar(metadados, [d.get("nome") or "" for d in documentos])

    pasta = destino / nome_da_pasta(numero, documentos)
    manifesto = mf.Manifesto(numero, "timeline_ng2" if ng2 else "timeline", pasta, id_proc)
    if ng2:
        manifesto.avisar("autos abertos na interface ng2 (Angular); enumeração por "
                         "span.documento-nome no iframe ngFrame (peças e anexos), "
                         "completude aferida pelos índices contíguos de 1 a N e pelo "
                         "contador do PJe")
    manifesto.registrar_materia(metadados, deteccao)
    manifesto.registrar_paginacao(pag)
    manifesto.enumerados = len(documentos)
    manifesto.duplicatas_descartadas = duplicatas

    if not pag.get("convergiu"):
        manifesto.avisar(f"paginação não convergiu: {pag.get('motivo_parada')}")
    if not id_proc:
        manifesto.avisar("identificador interno do processo não localizado; usando URL curta")
    if not documentos:
        manifesto.erro_fatal = "nenhum documento encontrado na timeline"
        return manifesto

    corte = tl.indice_da_sentenca(documentos)
    if corte is None:
        manifesto.avisar("sentença não localizada na timeline; todas as peças foram para "
                         "sentenca_em_diante/")
        corte = len(documentos)
    manifesto.paginacao["sentencas_detectadas"] = tl.sentencas_detectadas(documentos)

    antes = pasta / "antes_sentenca"
    depois = pasta / "sentenca_em_diante"
    antes.mkdir(parents=True, exist_ok=True)
    depois.mkdir(parents=True, exist_ok=True)

    registrar(f"Baixando {len(documentos)} peças para {pasta}")
    for i, doc in enumerate(documentos, 1):
        alvo_pasta = antes if doc["ordem"] > corte else depois
        base = f"{doc['ordem_crono']:03d}_{tl.limpar_nome_arquivo(doc['nome'])}_{doc['id']}"
        resultado = tl.baixar_documento(
            painel.contexto, HOST_PJE,
            doc["id"], id_proc, alvo_pasta / base, log=registrar)

        manifesto.registrar_documento({
            "id": doc["id"], "nome": doc["nome"], "ordem": doc["ordem"],
            "ordem_crono": doc["ordem_crono"], **resultado})

        if i % 25 == 0 or i == len(documentos):
            registrar(f"  {i}/{len(documentos)} — {manifesto.baixado} ok, "
                      f"{manifesto.falhas} falha(s)")

    return manifesto


def processar(numero: str, args) -> mf.Manifesto:
    destino = Path(args.destino).expanduser() if args.destino else cfg_unidade.pasta_downloads()
    manifesto = None
    painel = PainelPJe(headless=args.headless, perfil=args.perfil,
                       destino=destino, log=registrar)
    try:
        painel.iniciar()
        if not painel.login(espera_2fa=args.espera_login):
            raise RuntimeError("falha no login")
        if not painel.abrir_painel():
            raise RuntimeError("falha ao abrir o painel")
        if not painel.selecionar_perfil():
            raise RuntimeError("localização (perfil) configurada não encontrada no PJe")
        if not painel.buscar_processo(numero):
            raise RuntimeError("processo não localizado no painel")
        if not painel.abrir_autos(numero):
            raise RuntimeError("falha ao abrir os autos digitais")

        ng2 = bool(getattr(painel, "interface_ng2", False))
        if ng2 and args.rota == "autos":
            registrar("AVISO: a interface ng2 não tem o menu de download dos autos "
                      "completos; usando a enumeração ng2, que traz o histórico inteiro.")

        if args.rota in ("timeline", "auto") or ng2:
            manifesto = baixar_pela_timeline(painel, numero, destino)
            if ng2 and args.rota == "autos":
                manifesto.avisar("--rota autos pedida, mas a interface ng2 não oferece o "
                                 "PDF consolidado; baixado pela enumeração ng2")

        # Na ng2 a rota de autos completos nao existe: o menu classico sumiu e
        # a enumeracao ja cobre o processo inteiro.
        precisa_autos = not ng2 and (args.rota == "autos" or (
            args.rota == "auto" and manifesto is not None
            and manifesto.indicio_historico_truncado))

        if precisa_autos:
            import autos_completos
            if manifesto is not None:
                manifesto.avisar("indício de histórico truncado: acionada a rota de autos "
                                 "completos")
                manifesto.salvar()
            registrar("Acionando a rota de autos completos (PDF consolidado)...")
            manifesto = autos_completos.baixar(painel, numero, destino, log=registrar,
                                               manifesto_timeline=manifesto)

        return manifesto

    except Exception as exc:
        registrar(f"ERRO: {exc}")
        if manifesto is None:
            manifesto = mf.Manifesto(numero, args.rota,
                                     destino / tl.limpar_nome_arquivo(numero, 80))
        manifesto.erro_fatal = str(exc)
        return manifesto
    finally:
        try:
            if manifesto is not None:
                caminho = manifesto.salvar()
                registrar(f"Manifesto: {caminho}")
                registrar(manifesto.resumo())
        except Exception as exc:
            registrar(f"ERRO ao salvar o manifesto: {exc}")
        painel.fechar()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download íntegro de processos do PJe via painel interno.")
    parser.add_argument("processos", nargs="+",
                        help="números CNJ ou arquivo com um número por linha")
    parser.add_argument("--destino", default=None,
                        help="pasta de destino (padrão: a pasta de downloads da configuração)")
    parser.add_argument("--rota", choices=("auto", "timeline", "autos"), default="auto",
                        help="auto: timeline e, se houver indício de histórico truncado, "
                             "autos completos")
    parser.add_argument("--perfil", default=None, help="trecho da localização no PJe (padrão: a da configuração)")
    parser.add_argument("--headless", action="store_true",
                        help="sem janela; exige sessão válida, pois o segundo fator é manual")
    parser.add_argument("--espera-login", type=int, default=900,
                        help="segundos de espera pelo segundo fator (padrão: 900)")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    cfg_unidade.utf8_no_console()
    cfg_unidade.garantir_ambiente("playwright", "pypdf")
    tl.CONTEXTO = cfg_unidade.contexto_web()
    tl.SEGMENTO = cfg_unidade.pje()["segmento_download"]

    numeros = resolver_processos(args.processos)
    if not numeros:
        registrar("Nenhum número de processo válido.")
        return 1

    registrar(f"{len(numeros)} processo(s) | rota: {args.rota}")
    resultados = []
    for i, numero in enumerate(numeros, 1):
        registrar("=" * 70)
        registrar(f"[{i}/{len(numeros)}] {numero}")
        registrar("=" * 70)
        resultados.append(processar(numero, args))

    print("\n" + "=" * 70)
    print(" RELATÓRIO FINAL")
    print("=" * 70)
    completos = parciais = erros = 0
    for r in resultados:
        if r is None:
            erros += 1
            continue
        if r.erro_fatal:
            erros += 1
            marca = "ERRO"
        elif r.completo:
            completos += 1
            marca = "COMPLETO"
        else:
            parciais += 1
            marca = "INCOMPLETO"
        print(f"  [{marca}] {r.processo} — {r.resumo()}")
        if r.erro_fatal:
            print(f"           {r.erro_fatal}")
    print(f"\n  completos: {completos} | incompletos: {parciais} | erros: {erros}")
    print("=" * 70)

    if erros:
        return 1
    if parciais:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
