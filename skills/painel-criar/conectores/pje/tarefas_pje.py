"""
Navegação nas PASTAS DE TAREFA do Painel do Usuário Interno do PJe.

Tudo roda por `frame.evaluate` no iframe `ngFrame` (cross-origin). Os seletores
da árvore de tarefas foram verificados na captura 01_sessoes.html (23/08/2026);
os da lista de processos de uma pasta aberta são heurísticos até que o modo
`--diagnostico` de listar_tarefas_pje.py os confirme (ver referencias/seletores-tarefas.md).

ROTA PRINCIPAL (verificada em 14/10/2026): o ícone "Baixar lista de processos"
(`i.actionBaixarProcessos`) ao lado de cada pasta exporta um CSV com TODOS os
processos da pasta (separador ";", UTF-8 com BOM); `exportar_csv` + `parsear_csv`
dispensam a paginação. A enumeração por cards fica como reserva.

SOMENTE NAVEGAÇÃO: só se clica (1) no link de uma pasta na árvore, (2) no ícone
de exportação da pasta, (3) em controle de paginação fora de qualquer card e
(4) no select de tamanho de página. Nada dentro de card (checkbox, link do
processo, "Abrir autos", "Criar lembrete", "×" de etiqueta) é clicado.
"""

import csv
import math
import re
import sys
import time
import unicodedata
from pathlib import Path
from typing import Callable, Dict, List, Optional

PADRAO_CNJ = re.compile(r"\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import unidade as cfg_unidade  # noqa: E402


def _id_de(nome: str) -> str:
    base = re.sub(r"\[[^\]]*\]", "", nome)
    base = unicodedata.normalize("NFD", base)
    base = "".join(c for c in base if unicodedata.category(c) != "Mn").lower()
    return re.sub(r"[^a-z0-9]+", "-", base).strip("-") or "pasta"


def normalizar_pastas(lista: list) -> list:
    """Aceita nomes soltos ou dicionários e devolve [{id, nome, sigla}] sem ids repetidos."""
    saida, vistos = [], set()
    for item in lista or []:
        nome = item if isinstance(item, str) else item.get("nome", "")
        if not nome:
            continue
        ident = (item.get("id") if isinstance(item, dict) else None) or _id_de(nome)
        while ident in vistos:
            ident += "-2"
        vistos.add(ident)
        sigla = (item.get("sigla") if isinstance(item, dict) else None) \
            or re.sub(r"\s*\[[^\]]*\]", "", nome)[:14]
        saida.append({"id": ident, "nome": nome, "sigla": sigla})
    return saida


# Pastas de tarefa da unidade, na ordem de prioridade para deduplicação. Vêm da
# configuração (pje.pastas_tarefa), gravada pelo assistente de conexão; se
# estiver vazia, listar_tarefas_pje.py usa todas as pastas que o painel mostrar.
PASTAS = normalizar_pastas(cfg_unidade.pje().get("pastas_tarefa"))


def pastas_da_arvore(frame, arvore: str) -> list:
    """Todas as pastas que a árvore do painel mostra, no formato de PASTAS."""
    return normalizar_pastas([i["nome"] for i in listar_arvore(frame, arvore) if i.get("nome")])

ARVORES = {
    "todas": {"li": "#liTarefas", "href": "/lista-processos-tarefa/", "rotulo": "Tarefas"},
    "minhas": {"li": "#liMinhasTarefas", "href": "/lista-minhas-tarefas/", "rotulo": "Minhas tarefas"},
}
PREFIXO_HREF = "#/painel-usuario-interno/lista-"

LISTA_NEGRA = (
    "ASSINAR", "MOVIMENTAR", "ENCAMINHAR", "TRAMITAR", "SALVAR", "CONFIRMAR", "EXCLUIR",
    "REMOVER", "REDISTRIBUIR", "JUNTAR", "ANEXAR", "ENVIAR", "REGISTRAR", "LANCAR",
    "CONCLUIR", "FINALIZAR", "DEVOLVER", "ARQUIVAR", "SELECIONAR TODOS", "ABRIR TAREFA",
    "EXECUTAR", "ATRIBUIR", "LIMPAR", "PROFERIR", "VOTAR", "ACOMPANHO", "DIVIRJO",
)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[\u2010-\u2015\u2212]", "-", s)  # hífen, traço, travessão e sinal de menos valem o mesmo
    return re.sub(r"\s+", " ", s).strip().upper()


def proibido(texto: str) -> bool:
    t = _norm(texto)
    return any(p in t for p in LISTA_NEGRA)


def _log(fn, msg):
    (fn or print)(msg)


JS_UTIL = r"""
const vis = (el) => !!el && (el.offsetParent !== null || el.getClientRects().length > 0);
const norm = (s) => (s || '').normalize('NFD').replace(/[̀-ͯ]/g, '')
    .replace(/[\u2010-\u2015\u2212]/g, '-').replace(/\s+/g, ' ').trim().toUpperCase();
const txt = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
const rect = (el) => { const r = el.getBoundingClientRect();
    return {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)}; };
const clsDe = (el) => (el.className && el.className.baseVal !== undefined
    ? el.className.baseVal : el.className || '').toString();
const desc = (el) => ({tag: el.tagName, id: el.id || '', cls: clsDe(el).slice(0, 120),
    title: el.getAttribute('title') || el.getAttribute('aria-label') || el.getAttribute('tooltip') || '',
    texto: txt(el).slice(0, 160), ...rect(el)});
const NEGRA = %s;
const proibido = (s) => { const t = norm(s); return NEGRA.some(p => t.includes(p)); };
const RE_CNJ = /\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}/g;
const ARVORE_SEL = '#liTarefas, #liMinhasTarefas';
const dentroArvore = (el) => !!el.closest(ARVORE_SEL);
const PREFIXO_HREF = '#/painel-usuario-interno/lista-';
const nomeIgual = (a, b) => norm(a).replace(/\s*\[/g, '[') === norm(b).replace(/\s*\[/g, '[');
""" % (list(LISTA_NEGRA),)


def _ev(frame, js: str, arg=None):
    return frame.evaluate("(arg) => {" + JS_UTIL + js + "}", arg)


# ----------------------------------------------------------------- árvore

def listar_arvore(frame, arvore: str) -> list:
    """Pastas (tarefas) da árvore indicada: nome, href, quantidade."""
    return _ev(frame, r"""
        const raiz = document.querySelector(arg.li);
        if (!raiz) return [];
        const saida = [];
        for (const a of raiz.querySelectorAll('a[href]')) {
          const href = a.getAttribute('href') || '';
          if (!href.startsWith(PREFIXO_HREF)) continue;
          const item = a.closest('.menuItem') || a.parentElement;
          const q = item ? item.querySelector('.quantidadeTarefa') : null;
          const n = item ? item.querySelector('.nome') : null;
          saida.push({nome: a.getAttribute('title') || (n ? txt(n) : txt(a)), nome_span: n ? txt(n) : '',
                      href, quantidade: q ? parseInt(txt(q), 10) : null,
                      tem_baixar: !!(item && item.querySelector('.actionBaixarProcessos')), visivel: vis(a)});
        }
        return saida;
    """, {"li": ARVORES[arvore]["li"]})


def localizar_pasta(frame, arvore: str, nome: str) -> dict:
    """Localiza o <a> da pasta sem clicar: title exato, depois nome normalizado, depois href."""
    return _ev(frame, r"""
        const raiz = document.querySelector(arg.li);
        if (!raiz) return {ok: false, motivo: 'árvore ' + arg.li + ' ausente'};
        const links = [...raiz.querySelectorAll('a[href]')].filter(a => (a.getAttribute('href') || '').startsWith(PREFIXO_HREF));
        const info = (a, via) => {
          const item = a.closest('.menuItem') || a.parentElement;
          const q = item ? item.querySelector('.quantidadeTarefa') : null;
          return {ok: true, via, href: a.getAttribute('href'), title: a.getAttribute('title') || '',
                  quantidade: q ? parseInt(txt(q), 10) : null, visivel: vis(a)};
        };
        let a = links.find(l => (l.getAttribute('title') || '') === arg.nome);
        if (a) return info(a, 'title');
        a = links.find(l => nomeIgual(l.getAttribute('title') || txt(l), arg.nome));
        if (a) return info(a, 'nome normalizado');
        const alvo = norm(arg.nome).replace(/\s*\[/g, '[');
        a = links.find(l => { try { return norm(decodeURIComponent(l.getAttribute('href'))).replace(/\s*\[/g, '[').includes(alvo); } catch (e) { return false; } });
        if (a) return info(a, 'href');
        return {ok: false, motivo: 'pasta não encontrada', candidatos: links.slice(0, 40).map(l => l.getAttribute('title') || txt(l))};
    """, {"li": ARVORES[arvore]["li"], "nome": nome})


def ler_contador_arvore(frame, arvore: str, nome: str) -> Optional[int]:
    r = localizar_pasta(frame, arvore, nome)
    return r.get("quantidade") if r.get("ok") else None


def abrir_pasta(frame, arvore: str, nome: str, log=None) -> dict:
    """Clica no link da pasta. Reserva: location.hash dentro do frame; depois MouseEvent."""
    r = _ev(frame, r"""
        const raiz = document.querySelector(arg.li);
        if (!raiz) return {ok: false, motivo: 'árvore ausente'};
        const links = [...raiz.querySelectorAll('a[href]')].filter(a => (a.getAttribute('href') || '').startsWith(PREFIXO_HREF));
        let a = links.find(l => (l.getAttribute('title') || '') === arg.nome)
             || links.find(l => nomeIgual(l.getAttribute('title') || txt(l), arg.nome));
        if (!a) return {ok: false, motivo: 'pasta não encontrada'};
        if (proibido(a.getAttribute('title') + ' ' + txt(a))) return {ok: false, motivo: 'alvo na lista negra'};
        const href = a.getAttribute('href');
        const antes = location.hash;
        try { a.click(); } catch (e) {}
        return {ok: true, via: 'click', href, hash_antes: antes, hash_depois: location.hash};
    """, {"li": ARVORES[arvore]["li"], "nome": nome})
    _log(log, f"  abrir pasta: {r.get('ok')} via {r.get('via')} — {r.get('href', r.get('motivo'))}")
    if not r.get("ok"):
        return r
    # Se o hash não mudou, força pela rota interna do Angular.
    time.sleep(1.5)
    mudou = _ev(frame, "return {hash: location.hash};")
    if r["href"].lstrip("#") not in (mudou.get("hash") or ""):
        _ev(frame, "location.hash = arg; return true;", r["href"].lstrip("#"))
        r["via"] = "click+hash"
        _log(log, "  hash não mudou com o clique; aplicado location.hash")
    return r


# ----------------------------------------------------------------- lista da pasta

def esperar_lista(frame, nome: str, espera: int = 30, log=None) -> dict:
    """Espera a lista da pasta renderizar: cabeçalho com o nome e ≥1 CNJ fora da árvore (ou aviso de vazio)."""
    fim = time.time() + espera
    ultimo = {}
    while time.time() < fim:
        ultimo = _ev(frame, r"""
            const alvo = norm(arg).replace(/\s*\[/g, '[');
            let cabecalho = null, contador = null;
            for (const el of document.querySelectorAll('h1,h2,h3,h4,h5,h6,span,div,p,strong,label')) {
              if (dentroArvore(el) || !vis(el)) continue;
              const t = txt(el);
              if (t.length > 120) continue;
              if (norm(t).replace(/\s*\[/g, '[').includes(alvo)) { cabecalho = desc(el); 
                const cont = el.closest('div');
                const m = cont ? txt(cont).replace(t, '').match(/\b(\d{1,5})\b/) : null;
                if (m) contador = parseInt(m[1], 10);
                break; }
            }
            const cnjs = new Set();
            for (const el of document.querySelectorAll('a, span, div, td, strong, b')) {
              if (dentroArvore(el)) continue;
              const m = txt(el).match(RE_CNJ); if (m && txt(el).length < 200) m.forEach(x => cnjs.add(x));
            }
            const corpo = norm(document.body.innerText || '');
            const vazio = /NENHUM (PROCESSO|REGISTRO|RESULTADO)|NAO HA (PROCESSO|REGISTRO)|SEM PROCESSOS/.test(corpo);
            return {cabecalho, esperado_cabecalho: contador, n_cnj: cnjs.size, vazio, hash: location.hash};
        """, nome)
        if ultimo.get("cabecalho") and (ultimo.get("n_cnj", 0) > 0 or ultimo.get("vazio")):
            ultimo["ok"] = True
            return ultimo
        time.sleep(1)
    ultimo["ok"] = False
    _log(log, f"  AVISO: lista não confirmada em {espera}s: {ultimo}")
    return ultimo


def detectar_paginacao(frame) -> dict:
    """Controles de paginação e select de tamanho, por heurística genérica (fora da árvore e de cards)."""
    return _ev(frame, r"""
        const cands = [];
        const emCard = (el) => { const t = txt(el.closest('li, tr, .card, [class*="card"], [class*="processo"]') || el); return RE_CNJ.test(t) && !/PAGINA/.test(norm(clsDe(el))); };
        for (const el of document.querySelectorAll('a, button, li, span, i, div[role="button"], [class*="pagin"] *')) {
          if (dentroArvore(el) || !vis(el)) continue;
          const d = desc(el);
          const cls = (d.cls || '').toLowerCase();
          const filhoI = el.querySelector('i, svg, span');
          const clsI = (filhoI ? clsDe(filhoI) : '').toLowerCase();
          const chave = norm(d.title + ' ' + d.texto);
          const regiao = el.closest('[class*="pagin"], [class*="paginator"], [class*="pagination"], nav, [aria-label*="agina"]');
          let papel = null;
          if (/PROXIM|NEXT|SEGUINTE/.test(chave) || /angle-right|chevron-right|caret-right|pi-angle-right|step-forward(?!.*double)/.test(cls + ' ' + clsI)) papel = 'proximo';
          if (/ULTIM|LAST/.test(chave) || /angle-double-right|fast-forward|pi-angle-double-right/.test(cls + ' ' + clsI)) papel = 'ultimo';
          if (/PRIMEIR|FIRST/.test(chave) || /angle-double-left|fast-backward|pi-angle-double-left/.test(cls + ' ' + clsI)) papel = 'primeiro';
          if (/ANTERIOR|PREV/.test(chave) || /angle-left|chevron-left|caret-left|pi-angle-left|step-backward/.test(cls + ' ' + clsI)) papel = 'anterior';
          if (!papel && regiao && /^\d{1,3}$/.test(d.texto)) papel = 'pagina';
          if (!papel) continue;
          if (d.texto.length > 40 || emCard(el)) continue;
          const desab = el.disabled || el.getAttribute('aria-disabled') === 'true' || /disabled|ui-state-disabled|p-disabled/.test(cls)
                        || (el.parentElement && /disabled/.test(clsDe(el.parentElement).toLowerCase()));
          cands.push({papel, desabilitado: !!desab, regiao: !!regiao, ...d});
        }
        const selects = [];
        for (const s of document.querySelectorAll('select')) {
          if (dentroArvore(s) || !vis(s)) continue;
          const ops = [...s.options].map(o => parseInt(txt(o), 10)).filter(n => !isNaN(n));
          if (ops.length >= 2 && ops.every(n => n > 0 && n <= 1000)) selects.push({...desc(s), opcoes: ops, atual: parseInt(s.value, 10)});
        }
        const escolhe = (p) => { const l = cands.filter(c => c.papel === p); l.sort((a, b) => (a.regiao === b.regiao ? 0 : a.regiao ? -1 : 1) || b.y - a.y); return l[0] || null; };
        const atual = cands.find(c => c.papel === 'pagina' && /active|ativo|selected|current/.test((c.cls || '').toLowerCase()));
        return {proximo: escolhe('proximo'), anterior: escolhe('anterior'), primeiro: escolhe('primeiro'), ultimo: escolhe('ultimo'),
                pagina_atual: atual ? parseInt(atual.texto, 10) : null, paginas: cands.filter(c => c.papel === 'pagina').map(c => parseInt(c.texto, 10)),
                select: selects[0] || null, selects, candidatos: cands.slice(0, 30)};
    """)


def _clicar_por_desc(frame, d: dict, papel: str) -> dict:
    """Reencontra o elemento pela descrição (tag, classe, texto, posição) e clica se permitido."""
    return _ev(frame, r"""
        const d = arg.d;
        let melhor = null, melhorDist = 1e9;
        for (const el of document.querySelectorAll(d.tag)) {
          if (dentroArvore(el) || !vis(el)) continue;
          const e = desc(el);
          if (e.cls !== d.cls || e.texto !== d.texto || e.title !== d.title) continue;
          const dist = Math.abs(e.x - d.x) + Math.abs(e.y - d.y);
          if (dist < melhorDist) { melhor = el; melhorDist = dist; }
        }
        if (!melhor) return {ok: false, motivo: 'controle de paginação não reencontrado'};
        if (proibido(desc(melhor).title + ' ' + txt(melhor))) return {ok: false, motivo: 'alvo na lista negra'};
        if (RE_CNJ.test(txt(melhor))) return {ok: false, motivo: 'alvo contém CNJ (dentro de card)'};
        const alvo = melhor.closest('a, button') || melhor;
        alvo.click();
        return {ok: true, clicado: desc(alvo), papel: arg.papel};
    """, {"d": d, "papel": papel})


def primeiro_cnj(frame) -> Optional[str]:
    return _ev(frame, r"""
        for (const el of document.querySelectorAll('a, span, div, td, strong, b')) {
          if (dentroArvore(el) || !vis(el)) continue;
          const t = txt(el); if (t.length > 200) continue;
          const m = t.match(RE_CNJ); if (m) return m[0];
        }
        return null;
    """)


def contar_cnjs(frame) -> int:
    return _ev(frame, r"""
        const s = new Set();
        for (const el of document.querySelectorAll('a, span, div, td, strong, b')) {
          if (dentroArvore(el) || !vis(el)) continue;
          const t = txt(el); if (t.length > 200) continue;
          const m = t.match(RE_CNJ); if (m) m.forEach(x => s.add(x));
        }
        return s.size;
    """)


def esperar_rerender(frame, sentinela: Optional[str], n_antes: int, espera: int = 15) -> bool:
    fim = time.time() + espera
    while time.time() < fim:
        time.sleep(0.8)
        atual = primeiro_cnj(frame)
        if atual and atual != sentinela:
            time.sleep(1.0)
            return True
        if contar_cnjs(frame) not in (0, n_antes):
            time.sleep(1.0)
            return True
    return False


def definir_tamanho_pagina(frame, log=None) -> dict:
    pag = detectar_paginacao(frame)
    sel = pag.get("select")
    if not sel:
        _log(log, "  sem select de tamanho de página; mantém o padrão")
        return {"ok": False, "motivo": "sem select", "de": None, "para": None}
    maior = max(sel["opcoes"])
    if sel.get("atual") == maior:
        return {"ok": True, "de": sel.get("atual"), "para": maior, "inalterado": True}
    sentinela, n_antes = primeiro_cnj(frame), contar_cnjs(frame)
    r = _ev(frame, r"""
        const d = arg.d;
        for (const s of document.querySelectorAll('select')) {
          if (dentroArvore(s) || !vis(s)) continue;
          const e = desc(s);
          if (e.cls !== d.cls || Math.abs(e.y - d.y) > 40) continue;
          const op = [...s.options].find(o => parseInt(txt(o), 10) === arg.valor);
          if (!op) return {ok: false, motivo: 'opção ausente'};
          s.value = op.value;
          s.dispatchEvent(new Event('input', {bubbles: true}));
          s.dispatchEvent(new Event('change', {bubbles: true}));
          return {ok: true};
        }
        return {ok: false, motivo: 'select não reencontrado'};
    """, {"d": sel, "valor": maior})
    if r.get("ok"):
        esperar_rerender(frame, sentinela, n_antes, espera=20)
    _log(log, f"  tamanho de página: {sel.get('atual')} → {maior} ({r.get('ok')})")
    return {"ok": bool(r.get("ok")), "de": sel.get("atual"), "para": maior if r.get("ok") else sel.get("atual")}


def enumerar_cards(frame, com_html: int = 0) -> list:
    """Cards da lista aberta. Raiz do card = maior ancestral com exatamente um CNJ e texto < 2000 chars."""
    return _ev(frame, r"""
        const folhas = [];
        for (const el of document.querySelectorAll('a, span, div, td, strong, b, label')) {
          if (dentroArvore(el) || !vis(el)) continue;
          const t = txt(el); if (t.length > 120) continue;
          const m = t.match(RE_CNJ); if (!m) continue;
          if ([...el.children].some(c => RE_CNJ.test(txt(c)))) continue;  // quer a folha
          folhas.push({el, cnj: m[0]});
        }
        const raizes = new Map();
        for (const f of folhas) {
          let el = f.el, raiz = f.el;
          while (el.parentElement && !dentroArvore(el.parentElement)) {
            const p = el.parentElement;
            const t = p.innerText || '';
            const n = (t.match(RE_CNJ) || []).length;
            if (n !== 1 || t.length > 2000) break;
            raiz = p; el = p;
          }
          if (!raizes.has(f.cnj)) raizes.set(f.cnj, raiz);
        }
        const saida = [];
        let pos = 0;
        for (const [cnj, raiz] of raizes) {
          pos += 1;
          const linhas = (raiz.innerText || '').split('\n').map(s => s.trim()).filter(Boolean);
          const iCnj = linhas.findIndex(l => l.includes(cnj));
          const lCnj = iCnj >= 0 ? linhas[iCnj] : '';
          const mSigla = lCnj.match(new RegExp('^([A-Za-zÀ-ú]{2,12})\\s+' + cnj.replace(/[.]/g, '\\.')));
          const depois = iCnj >= 0 ? linhas.slice(iCnj + 1) : linhas;
          const ult = linhas.find(l => /^[UÚ]LTIMA MOVIMENTA/i.test(l));
          const etiquetas = [...raiz.querySelectorAll('[class*="tag"], [class*="etiqueta"], [class*="label"], [class*="chip"], [class*="badge"]')]
              .map(e => txt(e).replace(/\s*[×x]\s*$/i, '').trim()).filter(s => s && s.length < 60 && !RE_CNJ.test(s));
          const prio = raiz.querySelector('[title*="riorid"], [title*="rgent"], [class*="priorid"], [class*="urgen"]');
          saida.push({
            numero: cnj, posicao: pos,
            classe_sigla: mSigla ? mSigla[1].toUpperCase() : null,
            assunto: depois.find(l => !/^[UÚ]LTIMA MOVIMENTA/i.test(l) && !/\sX\s/.test(l) && !/Gabinete|Turma|C[âa]mara|Vara/i.test(l) && !etiquetas.includes(l)) || null,
            orgao: linhas.find(l => /Gabinete|Turma|C[âa]mara|Vara/i.test(l)) || null,
            partes: linhas.find(l => /\sX\s/.test(l) && !/^[UÚ]LTIMA/i.test(l)) || null,
            ultima_movimentacao: ult ? ult.replace(/^[UÚ]LTIMA MOVIMENTA[ÇC][ÃA]O:?\s*/i, '') : null,
            etiquetas: [...new Set(etiquetas)],
            prioridade: prio ? (prio.getAttribute('title') || txt(prio)) : null,
            raiz: desc(raiz), linhas: linhas.slice(0, 12),
            html: arg.com_html && pos <= arg.com_html ? raiz.outerHTML.slice(0, 3000) : undefined,
          });
        }
        return saida;
    """, {"com_html": com_html})


def listar_clicaveis(frame) -> list:
    """Elementos clicáveis visíveis fora da árvore (alimenta a lista negra)."""
    return _ev(frame, r"""
        const saida = [];
        for (const el of document.querySelectorAll('a, button, input[type=checkbox], input[type=button], [role=button], select')) {
          if (dentroArvore(el) || !vis(el)) continue;
          const d = desc(el);
          saida.push({...d, negra: proibido(d.title + ' ' + d.texto), com_cnj: RE_CNJ.test(d.texto)});
        }
        return saida.slice(0, 80);
    """)


def avancar_pagina(frame, pag: dict, log=None) -> dict:
    prox = pag.get("proximo")
    if not prox:
        return {"ok": False, "motivo": "sem botão de próxima página"}
    if prox.get("desabilitado"):
        return {"ok": False, "motivo": "próxima página desabilitada"}
    r = _clicar_por_desc(frame, prox, "proximo")
    _log(log, f"  próxima página: {r.get('ok')} {r.get('motivo', '')}")
    return r


def rolar_lista_ate_convergir(frame, log=None, max_iter: int = 40, estagnacoes: int = 3, espera: float = 1.5) -> dict:
    """Reserva para lista com rolagem infinita: rola o contêiner com mais CNJs até estabilizar."""
    anterior, parado = -1, 0
    for i in range(max_iter):
        n = _ev(frame, r"""
            let melhor = null, maior = 0;
            for (const el of document.querySelectorAll('div, ul, section, main')) {
              if (dentroArvore(el)) continue;
              const st = getComputedStyle(el);
              if (!/auto|scroll/.test(st.overflowY)) continue;
              const n = ((el.innerText || '').match(RE_CNJ) || []).length;
              if (n > maior) { maior = n; melhor = el; }
            }
            if (melhor) melhor.scrollTop = melhor.scrollHeight; else window.scrollTo(0, document.body.scrollHeight);
            return maior;
        """)
        time.sleep(espera)
        atual = contar_cnjs(frame)
        if atual == anterior:
            parado += 1
            if parado >= estagnacoes:
                break
        else:
            parado = 0
        anterior = atual
    _log(log, f"  rolagem: {anterior} CNJs após {i + 1} iteração(ões)")
    return {"enumerados": anterior, "iteracoes": i + 1}


def enumerar_pasta(frame, pasta: dict, esperado: Optional[int], log=None, teto: Optional[int] = None) -> dict:
    """Percorre a lista da pasta até convergir (contagem == esperado) ou esgotar as páginas."""
    inicio = time.time()
    tam = definir_tamanho_pagina(frame, log)
    tamanho = tam.get("para") or 30
    if teto is None:
        teto = min(60, max(3, math.ceil((esperado or 0) / max(tamanho, 1)) + 2))
    itens: Dict[str, dict] = {}
    paginas, estagnadas, motivo, convergiu = 0, 0, "", False
    avisos: List[str] = []
    usou_rolagem = False
    while True:
        paginas += 1
        antes = len(itens)
        for c in enumerar_cards(frame):
            c["pagina"] = paginas
            itens.setdefault(c["numero"], c)
        _log(log, f"  página {paginas}: {len(itens)} acumulados" + (f" de {esperado}" if esperado else ""))
        if esperado is not None and len(itens) >= esperado:
            convergiu, motivo = True, "convergência"
            break
        pag = detectar_paginacao(frame)
        if not pag.get("proximo"):
            if not usou_rolagem:
                usou_rolagem = True
                r = rolar_lista_ate_convergir(frame, log)
                if r["enumerados"] > len(itens):
                    continue
            motivo = "sem paginação" if esperado is None else "sem próxima página"
            convergiu = esperado is None
            break
        if pag["proximo"].get("desabilitado"):
            motivo = "última página"
            convergiu = esperado is None or len(itens) >= esperado
            break
        if paginas >= teto:
            motivo = f"teto de iterações ({teto}) atingido"
            break
        if len(itens) == antes:
            estagnadas += 1
            if estagnadas >= 2:
                motivo = "estagnação (duas páginas sem processo novo)"
                break
        else:
            estagnadas = 0
        sentinela, n_antes = primeiro_cnj(frame), contar_cnjs(frame)
        r = avancar_pagina(frame, pag, log)
        if not r.get("ok"):
            motivo = r.get("motivo", "falha ao avançar")
            break
        if not esperar_rerender(frame, sentinela, n_antes):
            avisos.append(f"página {paginas + 1}: a lista não mudou após o clique")
    if esperado is not None and len(itens) > esperado:
        avisos.append(f"enumerados ({len(itens)}) acima do esperado ({esperado})")
    return {
        "itens": list(itens.values()), "enumerados": len(itens), "paginas_percorridas": paginas,
        "tamanho_pagina": tamanho, "convergiu": convergiu, "motivo_parada": motivo,
        "avisos": avisos, "duracao_s": round(time.time() - inicio, 1),
    }


# ----------------------------------------------------------------- diagnóstico

def _salvar_captura(painel, frame, destino: Path, nome: str, log=None) -> None:
    destino.mkdir(parents=True, exist_ok=True)
    try:
        (destino / f"{nome}.html").write_text(frame.content(), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        _log(log, f"  AVISO: não salvou HTML {nome}: {exc}")
    try:
        painel.pagina.screenshot(path=str(destino / f"{nome}.png"), full_page=True)
    except Exception as exc:  # noqa: BLE001
        _log(log, f"  AVISO: não salvou PNG {nome}: {exc}")


COLUNAS_CSV = ("poloAtivo", "poloPassivo", "numeroProcesso", "classeJudicial", "orgaoJulgador", "dataChegada",
               "diasChegada", "conferido", "nomeTarefa", "sigiloso", "prioridade", "tagsProcessoList",
               "assuntoPrincipal", "ultimoMovimento", "diasUltimoMovimento", "descricaoUltimoMovimento", "nivelAcesso")


def parsear_csv(caminho: Path) -> List[dict]:
    """Lê o CSV exportado pelo PJe (';', UTF-8 com BOM) e devolve itens no esquema da fila."""
    itens: List[dict] = []
    with open(caminho, "r", encoding="utf-8-sig", newline="") as fh:
        leitor = csv.DictReader(fh, delimiter=";")
        for pos, linha in enumerate(leitor, start=1):
            numero = (linha.get("numeroProcesso") or "").strip()
            if not PADRAO_CNJ.fullmatch(numero):
                continue
            etiquetas = [t.strip() for t in (linha.get("tagsProcessoList") or "").split(",") if t.strip()]
            sim = lambda k: (linha.get(k) or "").strip().lower() == "sim"  # noqa: E731
            ativo, passivo = (linha.get("poloAtivo") or "").strip(), (linha.get("poloPassivo") or "").strip()
            itens.append({
                "numero": numero, "posicao": pos, "pagina": 1,
                "classe_sigla": (linha.get("classeJudicial") or "").strip().upper() or None,
                "assunto": (linha.get("assuntoPrincipal") or "").strip() or None,
                "orgao": (linha.get("orgaoJulgador") or "").strip() or None,
                "partes": f"{ativo} X {passivo}" if (ativo or passivo) else None,
                "polo_ativo": ativo or None, "polo_passivo": passivo or None,
                "ultima_movimentacao": (linha.get("descricaoUltimoMovimento") or "").strip() or None,
                "ultimo_movimento_em": (linha.get("ultimoMovimento") or "").strip() or None,
                "dias_ultimo_movimento": _int_ou_none(linha.get("diasUltimoMovimento")),
                "data_chegada": (linha.get("dataChegada") or "").strip() or None,
                "dias_chegada": _int_ou_none(linha.get("diasChegada")),
                "conferido": sim("conferido"), "sigiloso": sim("sigiloso"),
                "prioridade": "prioritário" if sim("prioridade") else None,
                "nivel_acesso": (linha.get("nivelAcesso") or "").strip() or None,
                "etiquetas": etiquetas,
            })
    return itens


def _int_ou_none(v) -> Optional[int]:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def exportar_csv(painel, frame, arvore: str, nome: str, destino: Path, log=None, espera: int = 30) -> dict:
    """Rota principal: aciona o ícone 'Baixar lista de processos' da pasta e salva o CSV em `destino`."""
    r = tentar_baixar_lista(painel, frame, arvore, nome, destino, log, espera)
    if not r.get("ok"):
        return r
    try:
        r["itens"] = parsear_csv(Path(r["arquivo"]))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "motivo": f"CSV ilegível: {exc}", "arquivo": r.get("arquivo")}
    return r


def tentar_baixar_lista(painel, frame, arvore: str, nome: str, destino: Path, log=None, espera: int = 20) -> dict:
    """Aciona o ícone 'Baixar lista de processos' (i.actionBaixarProcessos) da pasta e captura o download."""
    destino.mkdir(parents=True, exist_ok=True)
    pagina = painel.pagina
    try:
        with pagina.expect_download(timeout=espera * 1000) as dl:
            r = _ev(frame, r"""
                const raiz = document.querySelector(arg.li);
                if (!raiz) return {ok: false, motivo: 'árvore ausente'};
                for (const a of raiz.querySelectorAll('a[href]')) {
                  if ((a.getAttribute('title') || '') !== arg.nome) continue;
                  const item = a.closest('.menuItem');
                  const ic = item ? item.querySelector('.actionBaixarProcessos') : null;
                  if (!ic) return {ok: false, motivo: 'ícone ausente'};
                  ic.click();
                  return {ok: true, icone: desc(ic)};
                }
                return {ok: false, motivo: 'pasta não encontrada'};
            """, {"li": ARVORES[arvore]["li"], "nome": nome})
            if not r.get("ok"):
                raise RuntimeError(r.get("motivo"))
        download = dl.value
        alvo = destino / f"lista_{re.sub(r'[^a-z0-9]+', '_', _norm(nome).lower())[:40]}.csv"
        download.save_as(str(alvo))
        cab = ""
        try:
            cab = alvo.read_text(encoding="utf-8", errors="replace")[:400]
        except Exception:  # noqa: BLE001
            pass
        _log(log, f"  download da lista: {alvo.name} ({alvo.stat().st_size} bytes)")
        return {"ok": True, "arquivo": str(alvo), "bytes": alvo.stat().st_size, "cabecalho_texto": cab}
    except Exception as exc:  # noqa: BLE001
        novas = [p.url[:120] for p in painel.contexto.pages if p is not pagina]
        _log(log, f"  download da lista: não houve ({str(exc)[:80]}); abas novas: {novas}")
        return {"ok": False, "motivo": str(exc)[:200], "abas_novas": novas}


def diagnosticar_pasta(painel, arvore: str, pasta: dict, destino: Path, indice: int, log=None) -> dict:
    """Abre a pasta, salva capturas e devolve tudo o que a enumeração precisará saber."""
    frame = painel.frame
    saida: Dict = {"pasta": pasta, "arvore": arvore}
    saida["localizacao"] = localizar_pasta(frame, arvore, pasta["nome"])
    _log(log, f"  localização: {saida['localizacao']}")
    if not saida["localizacao"].get("ok"):
        return saida
    saida["abertura"] = abrir_pasta(frame, arvore, pasta["nome"], log)
    time.sleep(8)
    frame = painel.frame
    prefixo = f"{indice:02d}_{pasta['id']}"
    _salvar_captura(painel, frame, destino, f"{prefixo}_lista", log)
    saida["lista"] = esperar_lista(frame, pasta["nome"], espera=10, log=log)
    saida["cnjs_visiveis"] = contar_cnjs(frame)
    saida["paginacao"] = detectar_paginacao(frame)
    cards = enumerar_cards(frame, com_html=2)
    saida["n_cards"] = len(cards)
    saida["cards_amostra"] = cards[:2]
    saida["clicaveis"] = listar_clicaveis(frame)
    _log(log, f"  lista: ok={saida['lista'].get('ok')} cabeçalho={bool(saida['lista'].get('cabecalho'))} "
              f"contador_cab={saida['lista'].get('esperado_cabecalho')} cnjs={saida['cnjs_visiveis']} cards={len(cards)}")
    pg = saida["paginacao"]
    _log(log, f"  paginação: próximo={'sim' if pg.get('proximo') else 'não'} select={pg.get('select') and pg['select'].get('opcoes')} "
              f"páginas={pg.get('paginas')} candidatos={len(pg.get('candidatos', []))}")
    for c in cards[:2]:
        _log(log, f"  card {c['posicao']}: {c['classe_sigla']} {c['numero']} | assunto={c['assunto']!r} | etiquetas={c['etiquetas']}")
    if pg.get("select"):
        saida["tamanho"] = definir_tamanho_pagina(frame, log)
        time.sleep(3)
        _salvar_captura(painel, frame, destino, f"{prefixo}_pagina_max", log)
        saida["cnjs_apos_tamanho"] = contar_cnjs(frame)
        _log(log, f"  após tamanho máximo: {saida['cnjs_apos_tamanho']} CNJs")
        pg = detectar_paginacao(frame)
    if pg.get("proximo") and not pg["proximo"].get("desabilitado"):
        sent, n_antes = primeiro_cnj(frame), contar_cnjs(frame)
        saida["avanco"] = avancar_pagina(frame, pg, log)
        mudou = esperar_rerender(frame, sent, n_antes)
        saida["avanco"]["mudou"] = mudou
        saida["avanco"]["primeiro_antes"] = sent
        saida["avanco"]["primeiro_depois"] = primeiro_cnj(frame)
        _salvar_captura(painel, frame, destino, f"{prefixo}_pagina2", log)
        _log(log, f"  página 2: mudou={mudou} ({sent} → {saida['avanco']['primeiro_depois']})")
    return saida
