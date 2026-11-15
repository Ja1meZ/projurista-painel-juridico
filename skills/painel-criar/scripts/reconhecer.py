#!/usr/bin/env python3
"""
Reconhecimento de telas: abre a ferramenta do usuário e grava "retratos" da estrutura
das páginas que ele indicar, para que o conector seja escrito sob medida.

    python reconhecer.py [--espera 900] [--automatico N]

Como funciona: uma janela do navegador abre no endereço da configuração. O usuário faz o
login e vai até a tela que quer mostrar (a lista de pastas de tarefa; depois, a lista de
processos de uma pasta). Em cada tela, ele clica no botão azul "Retratar esta tela", que
aparece no canto inferior direito. Ao terminar, clica em "Concluir".

O retrato guarda a ESTRUTURA da página (tabelas, listas repetidas, links com contador,
paginação, campos de formulário) e no máximo três linhas de amostra por lista, com texto
cortado. Fica em ~/.projurista/painel/reconhecimento/, acessível só ao usuário, e deve
ser apagado ao final (`python reconhecer.py --apagar`). Nada é enviado, clicado ou
alterado na ferramenta.

--automatico N: sem botão; tira um retrato a cada N segundos enquanto a tela mudar (use
se o botão não aparecer por restrição da página).
"""
import argparse
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "painel-juridico" / "scripts"))
try:
    import painel_base as pb
except ImportError:
    raise SystemExit("Não encontrei a skill painel-juridico ao lado desta. Rode o instalador do pacote.")

JS_BOTAO = r"""
(() => {
  if (window.top !== window || window.__painelBotao) return;
  window.__painelBotao = true;
  const montar = () => {
    if (!document.body || document.getElementById('__painel_caixa')) return;
    const caixa = document.createElement('div');
    caixa.id = '__painel_caixa';
    caixa.style.cssText = 'position:fixed;right:14px;bottom:14px;z-index:2147483647;display:flex;gap:6px;font:13px sans-serif';
    const botao = (texto, cor, acao) => {
      const b = document.createElement('button');
      b.type = 'button'; b.textContent = texto;
      b.style.cssText = 'padding:9px 14px;border:0;border-radius:8px;color:#fff;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.35);background:' + cor;
      b.addEventListener('click', ev => { ev.preventDefault(); ev.stopPropagation(); acao(b); });
      caixa.appendChild(b);
    };
    botao('Retratar esta tela', '#2f6fde', b => { window.__painelSinal('retratar'); b.textContent = 'Retratado ✓'; setTimeout(() => b.textContent = 'Retratar esta tela', 1500); });
    botao('Concluir', '#1f7a3a', () => window.__painelSinal('concluir'));
    document.body.appendChild(caixa);
  };
  montar();
  document.addEventListener('DOMContentLoaded', montar);
  setInterval(montar, 1500);
})();
"""

JS_RETRATO = r"""
(arg) => {
  const RE = new RegExp(arg.regex);
  const corta = (s, n) => { s = (s || '').replace(/\s+/g, ' ').trim(); return s.length > n ? s.slice(0, n) + '…' : s; };
  const vis = el => !!(el.offsetParent || el.getClientRects().length);
  const esc = s => (window.CSS && CSS.escape) ? CSS.escape(s) : s;
  const meu = el => el.id === '__painel_caixa' || !!el.closest('#__painel_caixa');
  const passo = el => {
    if (el.id && !/\d{4,}|:/.test(el.id)) return '#' + esc(el.id);
    let s = el.tagName.toLowerCase();
    const cls = [...el.classList].filter(c => !/\d{3,}|^ng-|^ui-state|active|selected|hover|focus/.test(c)).slice(0, 3);
    if (cls.length) s += '.' + cls.map(esc).join('.');
    return s;
  };
  const caminho = el => {
    const partes = [];
    for (let e = el, i = 0; e && e.nodeType === 1 && e !== document.body && i < 5; e = e.parentElement, i++) {
      const p = passo(e); partes.unshift(p);
      if (p.startsWith('#')) break;
    }
    return partes.join(' > ');
  };
  const esqueleto = (el, prof) => {
    if (prof > 4) return '';
    const filhos = [...el.children].slice(0, 8).map(f => esqueleto(f, prof + 1)).join('');
    const proprio = [...el.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join(' ');
    const attrs = ['title', 'href', 'data-id'].filter(a => el.hasAttribute(a)).map(a => ` ${a}="${corta(el.getAttribute(a), 30)}"`).join('');
    return `<${passo(el)}${attrs}>${corta(proprio, 40)}${filhos}</>`;
  };
  const r = {url: location.href, titulo: document.title, tabelas: [], listas: [], links_com_contador: [],
             paginacao: [], identificadores: [], formularios: [], quadros: []};

  for (const t of [...document.querySelectorAll('table')].filter(vis).slice(0, 12)) {
    if (meu(t)) continue;
    const linhas = [...t.querySelectorAll('tbody > tr, tr')].filter(tr => tr.querySelector('td'));
    if (linhas.length < 1) continue;
    r.tabelas.push({seletor: caminho(t), cabecalhos: [...t.querySelectorAll('th')].slice(0, 20).map(th => corta(th.innerText, 30)),
      n_linhas: linhas.length, seletor_linha: caminho(t) + ' tbody tr',
      classes_das_celulas: [...linhas[0].children].slice(0, 20).map(passo),
      amostra: linhas.slice(0, 3).map(tr => [...tr.children].slice(0, 20).map(td => corta(td.innerText, 40)))});
  }

  const vistos = new Set();
  for (const pai of document.querySelectorAll('ul, ol, div, section, tbody, nav')) {
    if (meu(pai) || !vis(pai) || pai.children.length < 3) continue;
    const grupos = {};
    for (const f of pai.children) { const k = f.tagName + '.' + [...f.classList].slice(0, 2).join('.'); (grupos[k] = grupos[k] || []).push(f); }
    for (const g of Object.values(grupos)) {
      if (g.length < 3 || g[0].tagName === 'TR' || g[0].tagName === 'OPTION' || g[0].tagName === 'SCRIPT') continue;
      const sel = caminho(pai) + ' > ' + passo(g[0]);
      if (vistos.has(sel) || corta(g[0].innerText, 10).length < 2) continue;
      vistos.add(sel);
      r.listas.push({seletor_item: sel, n_itens: g.length, tem_identificador: g.some(e => RE.test(e.innerText || '')),
        amostra_texto: g.slice(0, 3).map(e => corta(e.innerText, 110)), esqueleto: esqueleto(g[0], 0).slice(0, 1400)});
    }
  }
  r.listas.sort((a, b) => (b.tem_identificador - a.tem_identificador) || (b.n_itens - a.n_itens));
  r.listas = r.listas.slice(0, 25);

  for (const a of [...document.querySelectorAll('a, [role="treeitem"], [role="menuitem"], li')].filter(vis)) {
    if (meu(a) || a.children.length > 6) continue;
    const t = corta(a.innerText, 90);
    if (!t || t.length > 88 || !/\d/.test(t) || RE.test(t)) continue;
    if (a.tagName === 'LI' && a.querySelector('li')) continue;
    r.links_com_contador.push({texto: t, seletor: caminho(a), href: a.getAttribute && a.getAttribute('href') ? corta(a.getAttribute('href'), 90) : null,
                               esqueleto: esqueleto(a, 0).slice(0, 300)});
    if (r.links_com_contador.length >= 60) break;
  }

  for (const el of [...document.querySelectorAll('a, button, li, span, input[type="button"]')].filter(vis)) {
    if (meu(el)) continue;
    const t = corta(el.innerText || el.value || '', 30).toLowerCase();
    const marca = (el.className && el.className.baseVal === undefined ? el.className : '') + ' ' + (el.getAttribute('title') || '') + ' ' + (el.getAttribute('aria-label') || '');
    if (/^(próxim|proxim|seguinte|avançar|>|»|›|>>)/.test(t) || /next|proxim|próxim|pagina|paginat|pager/i.test(marca))
      r.paginacao.push({texto: t, seletor: caminho(el), classe: corta(String(marca), 80), desabilitado: el.disabled || /disabled/.test(String(marca))});
    if (r.paginacao.length >= 25) break;
  }
  for (const el of document.querySelectorAll('body *')) {
    if (el.children.length || meu(el)) continue;
    const m = (el.textContent || '').match(RE);
    if (m) { r.identificadores.push({texto: m[0], seletor: caminho(el)}); if (r.identificadores.length >= 6) break; }
  }
  for (const f of [...document.querySelectorAll('form')].filter(vis).slice(0, 5))
    r.formularios.push({seletor: caminho(f), campos: [...f.querySelectorAll('input, select, button')].filter(vis).slice(0, 15)
      .map(i => ({tag: i.tagName.toLowerCase(), tipo: i.type || '', id: i.id || '', nome: i.name || '', texto: corta(i.innerText || i.value && i.type !== 'password' && i.type !== 'text' ? (i.innerText || '') : '', 30)}))});
  for (const q of document.querySelectorAll('iframe, frame'))
    r.quadros.push({seletor: caminho(q), id: q.id || '', nome: q.name || '', src: corta(q.getAttribute('src') || '', 90)});
  return r;
}
"""


def dizer(msg: str = "") -> None:
    print(msg, flush=True)


def retratar(nav, numero: int, regex: str) -> Path:
    quadros = []
    for f in nav.pagina.frames:
        try:
            dados = f.evaluate(JS_RETRATO, {"regex": regex})
        except Exception as exc:  # noqa: BLE001
            dados = {"url": f.url, "erro": str(exc)}
        dados["quadro_principal"] = f is nav.pagina.main_frame
        dados["nome_do_quadro"] = f.name
        if dados.get("erro") or any(dados.get(k) for k in ("tabelas", "listas", "links_com_contador", "formularios")):
            quadros.append(dados)
    arq = pb.dir_reconhecimento() / f"retrato-{numero:02d}.json"
    pb.gravar_json_atomico(arq, {"numero": numero, "url": nav.pagina.url,
                                 "titulo": nav.pagina.title(), "quadros": quadros})
    dizer(f"Retrato {numero} gravado: {arq} ({nav.pagina.url[:90]})")
    return arq


def main() -> int:
    pb.utf8_no_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--espera", type=int, default=900, help="tempo máximo da sessão, em segundos")
    ap.add_argument("--automatico", type=int, default=0, metavar="N")
    ap.add_argument("--apagar", action="store_true", help="apaga os retratos guardados e sai")
    args = ap.parse_args()

    pasta = pb.dir_reconhecimento()
    if args.apagar:
        shutil.rmtree(pasta, ignore_errors=True)
        dizer("Retratos apagados.")
        return 0
    for velho in pasta.glob("retrato-*.json"):
        velho.unlink()

    regex = (pb.carregar().get("identificador") or {}).get("regex") or pb.REGEX_CNJ
    sinais = []
    feitos = 0
    with pb.Navegador(log=dizer) as nav:
        if not args.automatico:
            nav.contexto.expose_binding("__painelSinal", lambda _fonte, s: sinais.append(s))
            nav.contexto.add_init_script(JS_BOTAO)
        nav.abrir()
        dizer(">>> Faça o login na janela, vá até a tela da fila e use os botões no canto inferior direito <<<"
              if not args.automatico else
              f">>> Faça o login e navegue; um retrato é tirado a cada {args.automatico}s quando a tela muda <<<")
        inicio, ultima = time.time(), ""
        while time.time() - inicio < args.espera:
            if not nav.contexto.pages:
                break
            nav.pagina = nav.contexto.pages[-1]
            if args.automatico:
                time.sleep(args.automatico)
                try:
                    assinatura = nav.pagina.url + str(nav.pagina.evaluate("() => document.body ? document.body.innerText.length : 0"))
                except Exception:  # noqa: BLE001
                    continue
                if assinatura != ultima and feitos < 12:
                    ultima = assinatura
                    feitos += 1
                    retratar(nav, feitos, regex)
                continue
            try:
                nav.pagina.wait_for_timeout(500)
            except Exception:  # noqa: BLE001
                break
            while sinais:
                s = sinais.pop(0)
                if s == "retratar":
                    feitos += 1
                    retratar(nav, feitos, regex)
                elif s == "concluir":
                    inicio = 0
        nav.salvar_sessao()
    resumo = {"retratos": feitos, "pasta": str(pasta)}
    dizer(json.dumps(resumo, ensure_ascii=False))
    if not feitos:
        dizer("Nenhum retrato foi tirado. Se o botão não apareceu, repita com --automatico 8.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
