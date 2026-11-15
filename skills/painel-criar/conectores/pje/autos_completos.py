"""
Rota de autos completos: aciona o "Download dos autos" do PJe e fatia o PDF
consolidado por marcadores, gerando um arquivo por peca.

Por que existe: a timeline expoe apenas as pecas da tarefa/fase atual. Mesmo com
a paginacao corrigida, um processo em fase avancada pode nao mostrar o historico
integral. O PDF consolidado traz os autos inteiros, com um marcador por peca.

Seletores verificados em 01/08/2026 contra a captura real da pagina de autos.
O acionador NAO tem texto: e um icone cujo rotulo esta no atributo `title`
("Download autos do processo"), dentro de `li.filtros-download`. Procurar por
textContent nao o encontra — foi assim que a primeira versao falhou.

Fluxo: abrir o menu suspenso -> clicar no botao "Download" de
`#navbar:botoesDownload`, que dispara o AJAX e depois aciona
`#navbar:downloadProcesso`.
"""

import re
import time
from pathlib import Path
from typing import Callable, Optional

import manifesto as mf
import timeline as tl

# Rotulos observados no PJe. O primeiro e o real, verificado; os demais sao
# tolerancia para variacoes entre versoes do sistema.
ROTULOS = (
    "download autos do processo",
    "download dos autos",
    "baixar autos",
    "download do processo",
    "baixar processo",
    "exportar autos",
)

ABRIR_MENU_JS = r"""(rotulos) => {
  const norm = (s) => (s || '').toLowerCase()
      .normalize('NFD').replace(/[\u0300-\u036f]/g, '').trim();
  // Caminho verificado: li.filtros-download > a.dropdown-toggle[title=...]
  let gatilho = document.querySelector('li.filtros-download > a, .filtros-download a.dropdown-toggle');
  if (!gatilho) {
    for (const el of document.querySelectorAll('a, button')) {
      const rot = norm(el.getAttribute('title')) + ' ' + norm(el.getAttribute('aria-label'));
      if (rotulos.some(r => rot.includes(norm(r)))) { gatilho = el; break; }
    }
  }
  if (!gatilho) return {ok: false, motivo: 'gatilho do menu de download não encontrado'};
  gatilho.click();
  return {ok: true, rotulo: gatilho.getAttribute('title') || '(sem title)'};
}"""

CONFIRMAR_JS = r"""() => {
  const alvos = [
    ...document.querySelectorAll('#navbar\\:botoesDownload input, #navbar\\:botoesDownload button'),
    ...document.querySelectorAll('.dropdown-menu input[type=button], .dropdown-menu button'),
  ];
  for (const el of alvos) {
    const v = (el.value || el.textContent || '').trim().toLowerCase();
    if (v === 'download' || v === 'baixar') {
      const r = el.getBoundingClientRect();
      if (r.width > 0 || el.offsetParent !== null) { el.click(); return {ok: true, rotulo: v}; }
    }
  }
  const direto = document.querySelector('#navbar\\:downloadProcesso');
  if (direto) { direto.click(); return {ok: true, rotulo: 'downloadProcesso (direto)'}; }
  return {ok: false, motivo: 'botão Download do menu não encontrado'};
}"""

LOCALIZAR_JS = r"""(rotulos) => {
  const norm = (s) => (s || '').toLowerCase()
      .normalize('NFD').replace(/[\u0300-\u036f]/g, '').trim();
  const achados = [];
  for (const el of document.querySelectorAll('a, button, span, li, div[role="menuitem"]')) {
    const t = norm(el.textContent);
    if (!t || t.length > 80) continue;
    for (const r of rotulos) {
      if (t.includes(norm(r))) {
        achados.push({rotulo: el.textContent.trim().slice(0, 60),
                      id: el.id || null, tag: el.tagName});
        break;
      }
    }
  }
  return achados;
}"""

CLICAR_JS = r"""(rotulos) => {
  const norm = (s) => (s || '').toLowerCase()
      .normalize('NFD').replace(/[\u0300-\u036f]/g, '').trim();
  for (const r of rotulos) {
    for (const el of document.querySelectorAll('a, button, span, li, div[role="menuitem"]')) {
      const t = norm(el.textContent);
      if (!t || t.length > 80) continue;
      if (t.includes(norm(r))) {
        (el.closest('a, button, li, div[role="menuitem"]') || el).click();
        return el.textContent.trim().slice(0, 60);
      }
    }
  }
  return null;
}"""

ABRIR_MENUS_JS = r"""() => {
  let abertos = 0;
  const alvos = document.querySelectorAll(
    '[data-toggle="dropdown"], [aria-haspopup="true"], .dropdown-toggle, '
    + 'button[title*="ções"], a[title*="ções"], .btn-menu, #menuAcoes');
  for (const el of alvos) { try { el.click(); abertos++; } catch (e) {} }
  return abertos;
}"""


def _sem_acentos(texto: str) -> str:
    import unicodedata
    d = unicodedata.normalize('NFKD', texto or '')
    return ''.join(c for c in d if not unicodedata.combining(c))


def _log(fn, msg):
    (fn or print)(msg)


def localizar_acionador(pagina, log=None) -> list:
    """Diagnostico: lista os elementos que casam os rotulos conhecidos."""
    try:
        return pagina.evaluate(LOCALIZAR_JS, list(ROTULOS))
    except Exception as exc:
        _log(log, f"AVISO: falha ao localizar o acionador: {exc}")
        return []


MSG_NG2 = ("os autos abriram na interface ng2 (Angular), que não tem o menu "
           "\"Download autos do processo\" da página clássica; a rota de autos "
           "completos não se aplica — use a rota timeline, que nessa interface "
           "enumera o histórico inteiro (rota timeline_ng2 no manifesto)")


def acionar_download(pagina, contexto, log=None, espera_ms: int = 600000):
    """Clica no acionador e captura o PDF consolidado.

    A geracao pode demorar bastante em processos volumosos: a espera padrao e
    de 10 minutos, e a falha e explicita, nunca silenciosa.
    """
    abertura = pagina.evaluate(ABRIR_MENU_JS, list(ROTULOS))
    if not abertura.get("ok"):
        raise RuntimeError(
            f"{abertura.get('motivo')}. Rótulos procurados: {', '.join(ROTULOS)}. "
            "O acionador é um ícone com o rótulo no atributo title, dentro de "
            "li.filtros-download — confira a página e atualize "
            "referencias/seletores-pje.md")

    _log(log, f"Menu de download aberto: {abertura.get('rotulo')!r}")
    time.sleep(2)

    with pagina.expect_download(timeout=espera_ms) as info:
        confirmacao = pagina.evaluate(CONFIRMAR_JS)
        if not confirmacao.get("ok"):
            raise RuntimeError(confirmacao.get("motivo"))
        _log(log, f"Solicitado ({confirmacao.get('rotulo')}). Aguardando a geração do "
                  f"PDF (até {espera_ms // 60000} min)...")
    return info.value


# Título de marcador do PJe: "Tipo da peça | NUM: 64471433 | 29/07/2026 12:40"
RE_TITULO_MARCADOR = re.compile(r"^(?P<nome>.+?)\s*\|\s*NUM:\s*(?P<id>\d+)\s*(?:\|.*)?$")
# Marcadores estruturais do PDF, que não são peças dos autos.
MARCADORES_NAO_PECA = {"cabecalho", "cabeçalho", "indice", "índice", "capa"}


def normalizar_arquivo_baixado(caminho: Path, log=None) -> Path:
    """O PJe entrega os autos como ZIP contendo um único PDF.

    Verificado em 01/08/2026: o download vem com assinatura `PK`, não `%PDF`.
    Salvar como .pdf sem checar produz um arquivo que o leitor rejeita com
    "Stream has ended unexpectedly" — erro que não sugere a causa real.
    """
    with open(caminho, "rb") as fh:
        assinatura = fh.read(4)

    if assinatura[:4] == b"%PDF":
        return caminho

    if assinatura[:2] != b"PK":
        raise RuntimeError(
            f"o arquivo baixado não é PDF nem ZIP (assinatura {assinatura!r}); "
            "verifique se o PJe não devolveu uma página de erro")

    import zipfile
    with zipfile.ZipFile(caminho) as pacote:
        pdfs = [n for n in pacote.namelist() if n.lower().endswith(".pdf")]
        if not pdfs:
            raise RuntimeError(f"o ZIP baixado não contém PDF: {pacote.namelist()[:5]}")
        if len(pdfs) > 1:
            _log(log, f"AVISO: o ZIP traz {len(pdfs)} PDFs; usando o maior")
            pdfs.sort(key=lambda n: pacote.getinfo(n).file_size, reverse=True)
        destino = caminho.with_name(caminho.stem + "_extraido.pdf")
        with pacote.open(pdfs[0]) as origem, open(destino, "wb") as saida:
            while True:
                bloco = origem.read(8 * 1024 * 1024)
                if not bloco:
                    break
                saida.write(bloco)
    _log(log, f"PDF extraído do ZIP: {destino.name} "
              f"({destino.stat().st_size / 1_048_576:.1f} MB)")
    return destino


def fatiar_por_marcadores(pdf: Path, pasta_saida: Path, log=None) -> list:
    """Divide o PDF consolidado em um arquivo por marcador.

    Marcador ausente e erro explicito: fatiar por adivinhacao produziria pecas
    silenciosamente erradas, que e justamente o defeito que esta skill combate.
    """
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError as exc:
        raise RuntimeError(f"pypdf é necessário para fatiar o PDF consolidado: {exc}")

    leitor = PdfReader(str(pdf))
    total_paginas = len(leitor.pages)
    marcadores = _achatar_marcadores(leitor)

    if not marcadores:
        raise RuntimeError(
            f"o PDF consolidado ({total_paginas} páginas) não tem marcadores; "
            "não é possível fatiar por peça sem adivinhar")

    marcadores.sort(key=lambda m: m["pagina"])
    pasta_saida.mkdir(parents=True, exist_ok=True)

    pecas = []
    descartados = 0
    for i, marcador in enumerate(marcadores):
        titulo = marcador["titulo"]
        casado = RE_TITULO_MARCADOR.match(titulo)
        nome_peca = casado.group("nome").strip() if casado else titulo
        id_peca = casado.group("id") if casado else f"m{i + 1:03d}"

        # Cabeçalho e Índice são estrutura do PDF, não peças dos autos.
        if not casado and _sem_acentos(nome_peca).lower() in MARCADORES_NAO_PECA:
            descartados += 1
            continue

        inicio = marcador["pagina"]
        fim = marcadores[i + 1]["pagina"] - 1 if i + 1 < len(marcadores) else total_paginas - 1
        if fim < inicio:
            fim = inicio

        escritor = PdfWriter()
        for p in range(inicio, fim + 1):
            escritor.add_page(leitor.pages[p])

        ordem = len(pecas)
        nome = f"{ordem + 1:03d}_{tl.limpar_nome_arquivo(nome_peca)}_{id_peca}.pdf"
        alvo = pasta_saida / nome
        with open(alvo, "wb") as fh:
            escritor.write(fh)

        pecas.append({
            "id": id_peca,
            "nome": nome_peca,
            "titulo_marcador": titulo,
            "ordem": ordem,
            "ordem_crono": ordem + 1,
            "destino": str(alvo),
            "formato": "pdf",
            "bytes": alvo.stat().st_size,
            "status": "ok",
            "tentativas": 1,
            "erro": None,
            "pagina_inicial": inicio + 1,
            "pagina_final": fim + 1,
        })

    if descartados:
        _log(log, f"{descartados} marcador(es) estrutural(is) ignorado(s) "
                  f"(cabeçalho, índice)")

    _log(log, f"PDF consolidado fatiado em {len(pecas)} peça(s) "
              f"a partir de {total_paginas} páginas")
    return pecas


def _achatar_marcadores(leitor) -> list:
    """Percorre a arvore de marcadores devolvendo titulo e pagina de cada um."""
    achatados = []

    def visitar(nos):
        for no in nos:
            if isinstance(no, list):
                visitar(no)
                continue
            try:
                titulo = str(getattr(no, "title", "") or "").strip()
                pagina = leitor.get_destination_page_number(no)
            except Exception:
                continue
            if titulo and isinstance(pagina, int):
                achatados.append({"titulo": titulo, "pagina": pagina})

    try:
        visitar(leitor.outline)
    except Exception:
        return []
    return achatados


def baixar(painel, numero: str, destino: Path, log: Optional[Callable] = None,
           manifesto_timeline: Optional[mf.Manifesto] = None) -> mf.Manifesto:
    """Fluxo completo da rota de autos completos."""
    if getattr(painel, "interface_ng2", False):
        # Na interface ng2 (Angular) nao existe o menu `li.filtros-download`.
        # O chamador deve usar a enumeracao ng2 da timeline, que ja traz o
        # historico inteiro. Ver referencias/seletores-pje.md.
        raise RuntimeError(MSG_NG2)
    pasta = destino / (tl.limpar_nome_arquivo(numero, 80) + " - autos completos")
    pasta.mkdir(parents=True, exist_ok=True)
    manifesto = mf.Manifesto(numero, "autos_completos", pasta, painel.id_processo())

    if manifesto_timeline is not None:
        manifesto.avisar("rota acionada após indício de histórico truncado na timeline")

    try:
        download = acionar_download(painel.popup, painel.contexto, log=log)
        baixado = pasta / f"{tl.limpar_nome_arquivo(numero, 60)}_autos_completos.download"
        download.save_as(str(baixado))
        _log(log, f"Arquivo recebido: {baixado.stat().st_size / 1_048_576:.1f} MB")

        consolidado = normalizar_arquivo_baixado(baixado, log=log)
        pecas = fatiar_por_marcadores(consolidado, pasta / "pecas", log=log)
        for peca in pecas:
            manifesto.registrar_documento(peca)

        manifesto.enumerados = len(pecas)
        manifesto.esperado = len(pecas)
        manifesto.registrar_paginacao({
            "convergiu": True,
            "motivo_parada": "PDF consolidado fatiado por marcadores",
            "origem": "autos_completos",
            "arquivo_consolidado": str(consolidado),
        })
    except Exception as exc:
        manifesto.erro_fatal = str(exc)
        _log(log, f"ERRO na rota de autos completos: {exc}")

    return manifesto
