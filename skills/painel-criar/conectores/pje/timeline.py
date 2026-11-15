"""
Timeline dos autos digitais do PJe: carregamento integral e download das pecas.

O defeito que este modulo existe para corrigir: a timeline pagina por AJAX
dentro de `div#divTimeLine:divEventosTimeLine.eventos-timeline.scroll-y`, que
tem barra de rolagem propria. Rolar a janela (`window.scrollBy`) nao dispara o
handler `carregaDataTimeLine`, entao so a primeira pagina carrega. Como a
timeline vem em ordem decrescente, sobram apenas os atos recentes.

Seletores verificados em 01/08/2026 — ver ../referencias/seletores-pje.md.
"""

import re
import time
from pathlib import Path
from typing import Callable, Optional

CONTAINER = "#divTimeLine\\:divEventosTimeLine, .eventos-timeline"

# Le, de uma vez, tudo que permite decidir se a timeline terminou de carregar.
# Reler a cada volta: o AJAX reescreve os hidden inputs.
ORACULO_JS = r"""() => {
  const cont = document.querySelector('#divTimeLine\\:divEventosTimeLine')
            || document.querySelector('.eventos-timeline');
  const num = (el) => {
    if (!el) return null;
    const v = parseInt((el.value !== undefined ? el.value : el.textContent) || '', 10);
    return Number.isNaN(v) ? null : v;
  };
  const cp = document.querySelector('span.contador-paginas');
  let carregados = null, total = null;
  if (cp) {
    const m = (cp.textContent || '').match(/(\d+)\s+de\s+(\d+)/);
    if (m) { carregados = parseInt(m[1], 10); total = parseInt(m[2], 10); }
  }
  const filtros = {};
  for (const n of ['chkExibirDocumentos','chkExibirMovimentos',
                   'chkExibirAudioVideo','chkExibirDocsExcluidos']) {
    const el = document.querySelector('[id$="' + n + '"]');
    filtros[n] = el ? !!el.checked : null;
  }
  // Conta ancoras cujo texto tem a forma "NNNNN - Tipo".
  let n_docs = 0;
  const re = /^(\d+)\s*-\s*(.+)/;
  const escopo = cont || document;
  for (const a of escopo.querySelectorAll('a')) {
    if (re.test((a.textContent || '').trim().replace(/\s+/g, ' '))) n_docs++;
  }
  return {
    container: !!cont,
    total_paginas: num(document.querySelector('#totalPaginas')),
    pagina_atual: num(document.querySelector('#paginaAtual')),
    contador_texto: cp ? cp.textContent.trim() : null,
    contador_carregados: carregados,
    contador_total: total,
    n_docs: n_docs,
    filtros: filtros,
    scroll_height: cont ? cont.scrollHeight : null,
    client_height: cont ? cont.clientHeight : null,
    tem_novaPagina: typeof novaPagina === 'function',
    tem_carregaData: typeof carregaDataTimeLine === 'function',
  };
}"""

# Avanco de pagina. Ordem: novaPagina() (caminho canonico, o proprio PJe rearma
# a paginacao no oncomplete) -> rolar o CONTAINER e disparar 'scroll' ->
# carregaDataTimeLine() direto.
AVANCAR_JS = r"""() => {
  if (typeof novaPagina === 'function') { novaPagina(); return 'novaPagina'; }
  const cont = document.querySelector('#divTimeLine\\:divEventosTimeLine')
            || document.querySelector('.eventos-timeline');
  if (cont) {
    cont.scrollTop = cont.scrollHeight;
    cont.dispatchEvent(new Event('scroll', {bubbles: true}));
    if (typeof carregaDataTimeLine === 'function') { carregaDataTimeLine(); }
    return 'scroll-container';
  }
  if (typeof carregaDataTimeLine === 'function') { carregaDataTimeLine(); return 'carregaData'; }
  return 'sem-acao';
}"""

# Enumeracao. NAO usar a[onclick*=abrirLinkDocumento] nem a[href*=/documento/download/]:
# ambos retornam zero (existem so dentro de <script>). NAO depender de a[id$=j_id384]:
# o sufixo JSF e volatil e cobre parte das ancoras.
ENUMERAR_JS = r"""() => {
  const cont = document.querySelector('#divTimeLine\\:divEventosTimeLine')
            || document.querySelector('.eventos-timeline')
            || document;
  const out = [];
  const re = /^(\d+)\s*-\s*(.+?)(?:\s*-\s*ID de origem.*)?$/;
  for (const a of cont.querySelectorAll('a')) {
    const texto = (a.textContent || '').trim().replace(/\s+/g, ' ');
    const m = texto.match(re);
    if (!m) continue;
    out.push({
      id: m[1],
      nome: (m[2] || '').trim(),
      texto_completo: texto.slice(0, 200),
      elemento_id: a.id || null,
    });
  }
  return out;
}"""


def _log(fn: Optional[Callable], msg: str):
    if fn:
        fn(msg)


def limpar_nome_arquivo(nome: str, limite: int = 150) -> str:
    """Nome seguro para o sistema de arquivos, preservando acentuacao."""
    nome = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", nome or "")
    nome = re.sub(r"\s+", "_", nome.strip())
    nome = nome.strip("._") or "documento"
    return nome[:limite]


def carregar_timeline_completa(page, log: Optional[Callable] = None,
                               max_iteracoes: int = 200,
                               max_estagnacoes: int = 3,
                               espera_ms: int = 20000) -> dict:
    """Avanca a paginacao ate convergir. Nunca prossegue em silencio.

    Devolve dict com o estado final, o motivo da parada e `convergiu`.
    """
    try:
        page.wait_for_selector(CONTAINER, timeout=30000)
    except Exception as exc:
        return {"convergiu": False, "motivo_parada": f"contêiner da timeline não encontrado: {exc}",
                "paginas_carregadas": 0, "iteracoes": 0}

    estado = page.evaluate(ORACULO_JS)
    if estado.get("filtros", {}).get("chkExibirDocumentos") is False:
        return {"convergiu": False,
                "motivo_parada": "filtro 'Exibir documentos' está desmarcado: a lista viria "
                                 "filtrada na origem",
                "paginas_carregadas": estado.get("pagina_atual") or 0,
                "iteracoes": 0, **_limpo(estado)}

    _log(log, f"Timeline: página {estado.get('pagina_atual')} de {estado.get('total_paginas')}, "
              f"{estado.get('n_docs')} documentos visíveis, "
              f"contador do PJe: {estado.get('contador_texto')}")

    estagnacoes = 0
    iteracoes = 0
    ultimo_n = estado.get("n_docs") or 0
    ultima_pag = estado.get("pagina_atual") or 0
    motivo = "convergência"
    acao = None

    while iteracoes < max_iteracoes:
        if _convergiu(estado):
            break

        iteracoes += 1
        try:
            acao = page.evaluate(AVANCAR_JS)
        except Exception as exc:
            motivo = f"falha ao avançar a paginação: {exc}"
            _log(log, f"AVISO: {motivo}")
            break

        if acao == "sem-acao":
            motivo = "nenhum mecanismo de avanço disponível na página"
            _log(log, f"AVISO: {motivo}")
            break

        # Espera por condicao: cresceu a contagem ou avancou a pagina.
        alvo_n, alvo_pag = ultimo_n, ultima_pag
        try:
            page.wait_for_function(
                """([n, p]) => {
                    const cont = document.querySelector('#divTimeLine\\\\:divEventosTimeLine')
                              || document.querySelector('.eventos-timeline') || document;
                    let c = 0; const re = /^(\\d+)\\s*-\\s*(.+)/;
                    for (const a of cont.querySelectorAll('a')) {
                      if (re.test((a.textContent||'').trim().replace(/\\s+/g,' '))) c++;
                    }
                    const pa = document.querySelector('#paginaAtual');
                    const pv = pa ? parseInt(pa.value || '0', 10) : 0;
                    return c > n || pv > p;
                }""",
                arg=[alvo_n, alvo_pag], timeout=espera_ms)
        except Exception:
            pass  # sem crescimento: tratado como estagnacao abaixo

        estado = page.evaluate(ORACULO_JS)
        n_atual = estado.get("n_docs") or 0
        pag_atual = estado.get("pagina_atual") or 0

        if n_atual > ultimo_n or pag_atual > ultima_pag:
            estagnacoes = 0
            _log(log, f"  página {pag_atual}/{estado.get('total_paginas')} — "
                      f"{n_atual} documentos (via {acao})")
        else:
            estagnacoes += 1
            if estagnacoes >= max_estagnacoes:
                motivo = (f"paginação estagnou após {estagnacoes} tentativas sem crescimento "
                          f"({n_atual} documentos)")
                _log(log, f"AVISO: {motivo}")
                break

        ultimo_n, ultima_pag = n_atual, pag_atual

    else:
        motivo = f"limite de {max_iteracoes} iterações atingido"
        _log(log, f"AVISO: {motivo}")

    convergiu = _convergiu(estado) and not motivo.startswith(("paginação estagnou",
                                                             "limite de", "falha", "nenhum",
                                                             "filtro"))
    resultado = {
        "convergiu": bool(convergiu),
        "motivo_parada": "convergência" if convergiu else motivo,
        "paginas_carregadas": estado.get("pagina_atual"),
        "iteracoes": iteracoes,
        "ultima_acao": acao,
        **_limpo(estado),
    }
    _log(log, f"Timeline carregada: {resultado['paginas_carregadas']} de "
              f"{resultado.get('total_paginas')} páginas, {resultado.get('n_docs')} documentos "
              f"— {resultado['motivo_parada']}")
    return resultado


def _limpo(estado: dict) -> dict:
    return {k: estado.get(k) for k in
            ("total_paginas", "pagina_atual", "contador_texto", "contador_carregados",
             "contador_total", "n_docs", "filtros")}


def _convergiu(estado: dict) -> bool:
    """Convergiu quando o PJe confirma que nao ha mais o que carregar."""
    tp = estado.get("total_paginas")
    pa = estado.get("pagina_atual")
    total = estado.get("contador_total")
    n = estado.get("n_docs") or 0

    if total is not None and n >= total:
        return True
    if tp is not None and pa is not None and pa >= tp:
        # Paginas esgotadas. Se ha contador e ele ainda nao bate, nao convergiu.
        if total is not None and n < total:
            return False
        return True
    return False


def enumerar_documentos(page, log: Optional[Callable] = None) -> tuple:
    """Enumera os documentos da timeline, deduplicando por identificador.

    Devolve (documentos, duplicatas_descartadas). A ordem preserva a da
    timeline (decrescente: mais recente primeiro).
    """
    brutos = page.evaluate(ENUMERAR_JS)
    vistos = {}
    duplicatas = 0
    for doc in brutos:
        ident = str(doc.get("id") or "").strip()
        if not ident:
            continue
        if ident in vistos:
            duplicatas += 1
            continue
        vistos[ident] = doc
    documentos = list(vistos.values())
    for ordem, doc in enumerate(documentos):
        doc["ordem"] = ordem
        doc["ordem_crono"] = len(documentos) - ordem
    _log(log, f"Enumerados {len(documentos)} documentos"
              + (f" ({duplicatas} duplicata(s) descartada(s))" if duplicatas else ""))
    return documentos, duplicatas


# --------------------------------------------------------------------------
# Interface ng2 (Angular) dos autos — verificada em 10/11/2026
#
# O PJe pode abrir os autos em `/ng2/dev.seam#/autos-digitais/N` (visto primeiro
# em processo fisico migrado; no mesmo dia, tambem em agravo comum),
# com o conteudo no iframe `ngFrame`. Ali nao ha `#divTimeLine`, `#totalPaginas`
# nem `span.contador-paginas`. Toda peca tem o nome em `span.documento-nome`, no
# formato "IDDOC - Tipo (descricao)", dentro de um de dois recipientes:
#   - peca principal: `div.documento-info`
#   - anexo da peca:  `div.row-grouped`, em `ul.tree-documentos-anexos`
# O atributo `id` do recipiente e o indice cronologico (1 = peca mais antiga),
# numerado em sequencia unica para principais e anexos.
# ARMADILHA: enumerar so `div.documento-info` perde TODOS os anexos (num agravo
# de 13 pecas, sobraram 3) — a enumeracao parte do `span.documento-nome`.
#
# Oraculo de completude: `span.contagem` ("12 de 13", title "Contagem de
# documentos") da o total do PJe; os indices devem ser contiguos de 1 ao total
# e a contagem deve ficar estavel apos rolar. Buraco na sequencia = peca nao
# carregada.

ENUMERAR_NG2_JS = r"""() => {
  const saida = [];
  for (const span of document.querySelectorAll('span.documento-nome')) {
    const info = span.closest('div.documento-info, div.row-grouped');
    if (!info) continue;
    const texto = (span.textContent || '').replace(/\s+/g, ' ').trim();
    const m = texto.match(/^(\d+)\s*-\s*(.+?)(?:\s*-\s*ID de origem.*)?$/);
    if (!m) continue;
    saida.push({id: m[1], nome: m[2].trim(), texto_completo: texto.slice(0, 200),
                elemento_id: info.id || null,
                anexo: info.classList.contains('row-grouped'),
                indice: /^\d+$/.test(info.id || '') ? parseInt(info.id, 10) : null});
  }
  return saida;
}"""

# Total anunciado pelo PJe no visualizador: "12 de 13".
CONTAGEM_NG2_JS = r"""() => {
  const el = document.querySelector('span.contagem');
  const m = el && (el.textContent || '').match(/(\d+)\s*de\s*(\d+)/);
  return m ? parseInt(m[2], 10) : null;
}"""

ROLAR_NG2_JS = r"""() => {
  let n = 0;
  for (const el of document.querySelectorAll('*')) {
    if (el.scrollHeight > el.clientHeight + 50) { el.scrollTop = el.scrollHeight; n++; }
  }
  window.scrollTo(0, document.body.scrollHeight);
  return n;
}"""


def _indices_contiguos(indices: list) -> bool:
    limpos = sorted(i for i in indices if isinstance(i, int))
    return bool(limpos) and limpos == list(range(1, len(limpos) + 1))


def carregar_documentos_ng2(frame, log: Optional[Callable] = None,
                            max_iteracoes: int = 60, leituras_estaveis: int = 3,
                            pausa: float = 2.5) -> dict:
    """Rola a lista de pecas da interface ng2 ate a contagem estabilizar.

    Devolve um dicionario no mesmo formato de `carregar_timeline_completa`
    (`convergiu`, `motivo_parada`, `contador_total`, `n_docs`...), para que o
    manifesto e o portao de completude funcionem sem ramificacao.
    """
    if frame is None:
        return {"convergiu": False, "interface": "ng2", "iteracoes": 0,
                "motivo_parada": "iframe ngFrame dos autos não localizado"}

    anterior, estaveis, iteracoes, brutos = -1, 0, 0, []
    for iteracoes in range(1, max_iteracoes + 1):
        try:
            frame.evaluate(ROLAR_NG2_JS)
        except Exception:
            pass
        time.sleep(pausa)
        brutos = frame.evaluate(ENUMERAR_NG2_JS)
        if len(brutos) == anterior:
            estaveis += 1
            if estaveis >= leituras_estaveis:
                break
        else:
            estaveis = 0
        anterior = len(brutos)

    indices = [d.get("indice") for d in brutos]
    com_indice = [i for i in indices if isinstance(i, int)]
    contiguos = _indices_contiguos(indices) and len(com_indice) == len(brutos)
    estavel = estaveis >= leituras_estaveis
    try:
        anunciado = frame.evaluate(CONTAGEM_NG2_JS)
    except Exception:
        anunciado = None
    maior = max(com_indice) if com_indice else None
    total = max(v for v in (anunciado, maior) if isinstance(v, int)) \
        if isinstance(anunciado, int) or isinstance(maior, int) else None
    bate_total = total is None or len(brutos) >= total

    if not brutos:
        motivo = "nenhuma peça (span.documento-nome) no iframe ngFrame"
    elif not estavel:
        motivo = f"contagem não estabilizou em {iteracoes} leituras"
    elif not contiguos:
        motivo = ("índices das peças não são contíguos de 1 a N: "
                  f"{len(brutos)} peças, maior índice {maior if maior else '?'}")
    elif not bate_total:
        motivo = f"{len(brutos)} peças enumeradas, mas o PJe anuncia {total}"
    else:
        motivo = ("contagem estável e índices contíguos de 1 a N"
                  + (f", conferidos com o contador do PJe ({anunciado})"
                     if isinstance(anunciado, int) else ""))

    resultado = {
        "interface": "ng2",
        "convergiu": bool(brutos) and estavel and contiguos and bate_total,
        "motivo_parada": motivo,
        "iteracoes": iteracoes,
        "n_docs": len(brutos),
        "n_anexos": sum(1 for d in brutos if d.get("anexo")),
        "contador_anunciado": anunciado,
        "contador_total": total,
        "contador_carregados": len(brutos),
    }
    _log(log, f"Interface ng2: {len(brutos)} peça(s) carregada(s) — {motivo}")
    return resultado


def enumerar_documentos_ng2(frame, log: Optional[Callable] = None) -> tuple:
    """Enumera as pecas da interface ng2, no mesmo formato de `enumerar_documentos`.

    A saida vem em ordem decrescente (mais recente primeiro, `ordem` 0), como na
    timeline classica, para que `indice_da_sentenca` conserve o significado.
    """
    brutos = frame.evaluate(ENUMERAR_NG2_JS) if frame is not None else []
    vistos = {}
    duplicatas = 0
    for doc in brutos:
        ident = str(doc.get("id") or "").strip()
        if not ident:
            continue
        if ident in vistos:
            duplicatas += 1
            continue
        vistos[ident] = doc
    documentos = list(vistos.values())

    # Com indice em todas as pecas, ele manda na ordem; senao vale a do DOM,
    # que a interface entrega em ordem decrescente.
    if documentos and all(isinstance(d.get("indice"), int) for d in documentos):
        documentos.sort(key=lambda d: d["indice"], reverse=True)
    for ordem, doc in enumerate(documentos):
        doc["ordem"] = ordem
        doc["ordem_crono"] = len(documentos) - ordem
    _log(log, f"Enumerados {len(documentos)} documentos (interface ng2)"
              + (f" ({duplicatas} duplicata(s) descartada(s))" if duplicatas else ""))
    return documentos, duplicatas


# Caminho da aplicação no servidor (ex.: "/pje") e segmento que alguns tribunais
# exigem no endereço de download ("SIGLA/grau"). Preenchidos por baixar_painel_pje.py
# a partir da configuração e da própria página dos autos.
CONTEXTO = ""
SEGMENTO = ""


def url_download(id_documento: str, id_processo: Optional[str]) -> str:
    raiz = f"{CONTEXTO}/seam/resource/rest/pje-legacy/documento/download"
    if id_processo and SEGMENTO:
        return f"{raiz}/{SEGMENTO}/{id_processo}/{id_documento}"
    return f"{raiz}/{id_documento}"


def _extensao(content_type: str, corpo: bytes) -> str:
    ct = (content_type or "").lower()
    if corpo[:4] == b"%PDF" or "application/pdf" in ct:
        return "pdf"
    if "html" in ct:
        return "html"
    if "xml" in ct:
        return "xml"
    if "image/jpeg" in ct:
        return "jpg"
    if "image/png" in ct:
        return "png"
    if "zip" in ct:
        return "zip"
    return "bin"


def _injetar_charset(html: str) -> str:
    if "charset" in html[:2000].lower():
        return html
    meta = '<meta charset="UTF-8">'
    if "<head>" in html:
        return html.replace("<head>", f"<head>{meta}", 1)
    idx = html.lower().find("<body")
    if idx >= 0:
        return html[:idx] + f"<head>{meta}</head>" + html[idx:]
    return f"<html><head>{meta}</head>{html}</html>"


def baixar_documento(context, base_url: str, id_documento: str, id_processo: Optional[str],
                     destino_sem_extensao: Path, tentativas: int = 3,
                     log: Optional[Callable] = None) -> dict:
    """Baixa uma peca por HTTP autenticado, com validacao e repeticao.

    Usa `context.request`, que compartilha os cookies do contexto: dispensa abrir
    e fechar abas, que e o que torna o download antigo lento (15 s de espera por
    peca) e instavel.
    """
    caminho = base_url.rstrip("/") + url_download(id_documento, id_processo)
    esperas = [1, 3, 8]
    ultimo_erro = None

    for tentativa in range(1, tentativas + 1):
        try:
            resp = context.request.get(caminho, timeout=60000)
            status = resp.status
            if status < 200 or status >= 300:
                ultimo_erro = f"HTTP {status}"
                raise RuntimeError(ultimo_erro)

            corpo = resp.body()
            if not corpo:
                ultimo_erro = "corpo vazio"
                raise RuntimeError(ultimo_erro)

            ct = (resp.headers or {}).get("content-type", "")
            ext = _extensao(ct, corpo)

            # Um HTML de erro ou de login servido com status 200 nao e a peca.
            if ext == "html":
                texto = corpo.decode("utf-8", errors="replace")
                baixo = texto.lower()
                if "sso.cloud.pje.jus.br" in baixo or 'id="kc-login"' in baixo:
                    ultimo_erro = "sessão expirada (HTML de login)"
                    raise RuntimeError(ultimo_erro)
                corpo = _injetar_charset(texto).encode("utf-8")

            alvo = destino_sem_extensao.with_suffix(f".{ext}")
            alvo.parent.mkdir(parents=True, exist_ok=True)
            alvo.write_bytes(corpo)

            return {"status": "ok", "destino": str(alvo), "formato": ext,
                    "bytes": len(corpo), "tentativas": tentativa, "erro": None,
                    "content_type": ct}

        except Exception as exc:
            ultimo_erro = str(exc)
            if tentativa < tentativas:
                time.sleep(esperas[min(tentativa - 1, len(esperas) - 1)])
            else:
                _log(log, f"  falha em {id_documento}: {ultimo_erro}")

    return {"status": "falha", "destino": None, "formato": None, "bytes": 0,
            "tentativas": tentativas, "erro": ultimo_erro, "content_type": None}


def indice_da_sentenca(documentos: list) -> Optional[int]:
    """Ordem do primeiro documento cujo nome indica sentenca.

    Com a timeline inteira, processos de varias fases tem mais de uma; a
    primeira encontrada e a mais recente, porque a timeline e decrescente.
    """
    for doc in documentos:
        nome = (doc.get("nome") or "").lower().strip()
        if nome.startswith("sentença") or nome.startswith("sentenca"):
            return doc.get("ordem")
    for doc in documentos:
        if "decisão interlocutória" in (doc.get("nome") or "").lower():
            return doc.get("ordem")
    return None


def sentencas_detectadas(documentos: list) -> list:
    achadas = []
    for doc in documentos:
        nome = (doc.get("nome") or "").lower()
        if nome.startswith("sentença") or nome.startswith("sentenca"):
            achadas.append({"id": doc.get("id"), "nome": doc.get("nome"),
                            "ordem": doc.get("ordem")})
    return achadas
