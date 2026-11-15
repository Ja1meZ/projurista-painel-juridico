#!/usr/bin/env python3
"""
Conector por receita — para qualquer ferramenta processual na web. Somente leitura.

Em vez de programar, descreva as telas num arquivo `receita.json` ao lado deste script
(veja `receita.exemplo.json` e docs/contrato-conector.md). O motor abre a ferramenta,
espera o login, percorre as pastas (ou filas, localizadores, caixas) e lê as linhas.

    python conector.py sondar [--saida ARQ]     lista as pastas e mostra 3 linhas de amostra
    python conector.py listar [--saida ARQ]     grava a fila no formato do painel

Códigos de saída: 0 completo, 1 erro, 2 parcial.

Se a ferramenta exigir algo que a receita não expressa, edite este arquivo — mantendo a
regra: todo clique passa por `pb.clicar_leitura`, que recusa botões de escrita.
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))

import _inicio  # noqa: E402,F401
import painel_base as pb  # noqa: E402

ARQ_RECEITA = AQUI / "receita.json"

# Extrai, dentro do navegador, as linhas de uma lista. Um "extrator" é
# {seletor?, atributo?, regex?}: sem seletor, usa a própria linha; sem atributo, o texto.
JS_LINHAS = r"""
(arg) => {
  const txt = el => (el ? (el.innerText || el.textContent || '') : '').replace(/\s+/g, ' ').trim();
  const extrair = (raiz, ex) => {
    if (!ex) return null;
    if (typeof ex === 'string') ex = {seletor: ex};
    let el = raiz;
    if (ex.seletor) { try { el = raiz.querySelector(ex.seletor); } catch (e) { return null; } }
    if (!el) return null;
    let v = ex.atributo ? (el.getAttribute(ex.atributo) || '') : txt(el);
    if (ex.regex) { const m = v.match(new RegExp(ex.regex)); v = m ? (m[1] !== undefined ? m[1] : m[0]) : ''; }
    return v.trim() || null;
  };
  let linhas;
  try { linhas = [...document.querySelectorAll(arg.linha)]; } catch (e) { return {erro: 'seletor de linha inválido: ' + e.message}; }
  const itens = linhas.map(l => {
    const campos = {};
    for (const [k, ex] of Object.entries(arg.campos || {})) { const v = extrair(l, ex); if (v) campos[k] = v; }
    return {identificador: extrair(l, arg.identificador), campos};
  });
  return {total_linhas: linhas.length, itens, total: arg.total ? extrair(document, arg.total) : null};
}
"""

JS_PASTAS = r"""
(arg) => {
  const txt = el => (el ? (el.innerText || el.textContent || '') : '').replace(/\s+/g, ' ').trim();
  const extrair = (raiz, ex) => {
    if (!ex) return null;
    if (typeof ex === 'string') ex = {seletor: ex};
    let el = raiz;
    if (ex.seletor) { try { el = raiz.querySelector(ex.seletor); } catch (e) { return null; } }
    if (!el) return null;
    let v = ex.atributo ? (el.getAttribute(ex.atributo) || '') : txt(el);
    if (ex.regex) { const m = v.match(new RegExp(ex.regex)); v = m ? (m[1] !== undefined ? m[1] : m[0]) : ''; }
    return v.trim() || null;
  };
  let els;
  try { els = [...document.querySelectorAll(arg.seletor)]; } catch (e) { return {erro: 'seletor de pastas inválido: ' + e.message}; }
  return {pastas: els.map((el, i) => {
    const link = el.matches('a[href]') ? el : el.querySelector('a[href]');
    return {indice: i, nome: extrair(el, arg.nome) || txt(el), quantidade: extrair(el, arg.quantidade),
            href: link ? link.getAttribute('href') : null};
  })};
}
"""


def dizer(msg: str = "") -> None:
    print(msg, flush=True)


def carregar_receita() -> dict:
    if not ARQ_RECEITA.is_file():
        raise SystemExit(f"Falta a receita: {ARQ_RECEITA}. Rode /painel-criar para construí-la.")
    try:
        return json.loads(ARQ_RECEITA.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise SystemExit(f"Receita ilegível ({ARQ_RECEITA}): {exc}")


def _inteiro(texto):
    if texto is None:
        return None
    m = re.search(r"\d[\d.]*", str(texto))
    return int(m.group(0).replace(".", "")) if m else None


class Motor:
    def __init__(self, nav: "pb.Navegador", receita: dict):
        self.nav, self.r = nav, receita
        self.regex = pb.regex_identificador(nav.conf)

    # -- onde ler: página ou quadro interno (iframe)
    def alvo(self):
        quadro = self.r.get("quadro")
        if not quadro:
            return self.nav.pagina
        el = self.nav.pagina.wait_for_selector(quadro, timeout=30000)
        return el.content_frame() or self.nav.pagina

    def _logado(self, pagina) -> bool:
        cond = self.r.get("logado") or {}
        url = pagina.url or ""
        if cond.get("url_contem") and cond["url_contem"] not in url:
            return False
        if cond.get("url_nao_contem") and cond["url_nao_contem"] in url:
            return False
        if cond.get("seletor"):
            for f in pagina.frames:
                try:
                    if f.locator(cond["seletor"]).count() > 0:
                        return True
                except Exception:
                    continue
            return False
        return bool(cond.get("url_contem") or cond.get("url_nao_contem"))

    def _preencher(self, pagina, usuario, senha) -> None:
        campos = self.r.get("login") or {}
        if not (campos.get("usuario") and campos.get("senha")):
            return
        pagina.fill(campos["usuario"], usuario)      # único preenchimento permitido: o login
        pagina.fill(campos["senha"], senha)
        if campos.get("entrar"):
            pagina.click(campos["entrar"])

    def entrar(self, espera: int) -> bool:
        self.nav.abrir()
        if not (self.r.get("logado") or {}):
            raise SystemExit("A receita precisa da seção 'logado' (como reconhecer que o login terminou).")
        if not self.nav.esperar_login(self._logado, espera=espera, preencher=self._preencher):
            return False
        self.passos(self.r.get("passos_iniciais"))
        return True

    def passos(self, passos) -> None:
        for p in passos or []:
            if p.get("ir"):
                self.nav.pagina.goto(urljoin(self.nav.url, p["ir"]), wait_until="domcontentloaded")
            if p.get("clicar"):
                pb.clicar_leitura(self.alvo().locator(p["clicar"]).first, self.nav.log)
            if p.get("esperar"):
                self.alvo().wait_for_selector(p["esperar"], timeout=int(p.get("tempo", 30)) * 1000)
            if p.get("pausa"):
                time.sleep(float(p["pausa"]))

    # -- pastas
    def pastas(self) -> list:
        fixas = self.r.get("pastas_fixas")
        if fixas:
            return [{"nome": f["nome"], "url": f.get("url"), "clicar": f.get("clicar"),
                     "quantidade": None, "indice": i} for i, f in enumerate(fixas)]
        desc = self.r.get("pastas") or {}
        if not desc.get("seletor"):
            raise SystemExit("A receita precisa de 'pastas' (com 'seletor') ou de 'pastas_fixas'.")
        res = self.alvo().evaluate(JS_PASTAS, desc)
        if res.get("erro"):
            raise SystemExit(res["erro"])
        saida = []
        for p in res["pastas"]:
            if p["nome"]:
                p["quantidade"] = _inteiro(p["quantidade"])
                saida.append(p)
        return saida

    def abrir_pasta(self, pasta: dict) -> None:
        desc = self.r.get("pastas") or {}
        if pasta.get("url"):
            self.nav.pagina.goto(urljoin(self.nav.url, pasta["url"]), wait_until="domcontentloaded")
        elif pasta.get("clicar"):
            pb.clicar_leitura(self.alvo().locator(pasta["clicar"]).first, self.nav.log, pasta=True)
        elif desc.get("abrir") == "href" and pasta.get("href"):
            self.nav.pagina.goto(urljoin(self.nav.pagina.url, pasta["href"]), wait_until="domcontentloaded")
        else:
            el = self.alvo().locator(desc["seletor"]).nth(pasta["indice"])
            link = el.locator("a").first if desc.get("clicar_no_link") else el
            pb.clicar_leitura(link, self.nav.log, pasta=True)
        lista = self.r.get("lista") or {}
        if lista.get("esperar"):
            try:
                # pasta que a ferramenta diz estar vazia não merece a espera longa
                self.alvo().wait_for_selector(
                    lista["esperar"], timeout=4000 if pasta.get("quantidade") == 0 else 30000)
            except Exception:
                pass
        time.sleep(float(lista.get("pausa", 1)))

    def voltar(self) -> None:
        if self.r.get("pastas_fixas"):
            return
        volta = (self.r.get("pastas") or {}).get("voltar")
        if volta:
            self.passos(volta if isinstance(volta, list) else [volta])
        else:
            self.passos(self.r.get("passos_iniciais") or [{"ir": self.nav.url}])

    # -- linhas
    def ler_pagina(self) -> dict:
        lista = self.r.get("lista") or {}
        if not lista.get("linha") or not lista.get("identificador"):
            raise SystemExit("A receita precisa de 'lista.linha' e 'lista.identificador'.")
        res = self.alvo().evaluate(JS_LINHAS, {k: lista.get(k) for k in ("linha", "identificador", "campos", "total")})
        if res.get("erro"):
            raise SystemExit(res["erro"])
        bons = []
        for it in res["itens"]:
            m = self.regex.search(it.get("identificador") or "")
            if m:
                it["identificador"] = m.group(0)
                bons.append(it)
        res["itens"] = bons
        return res

    def ler_pasta(self, teto_paginas: int = 300) -> dict:
        pag = self.r.get("paginacao") or {}
        vistos, itens, avisos, total = set(), [], [], None
        for n in range(1, teto_paginas + 1):
            res = self.ler_pagina()
            total = _inteiro(res.get("total")) if res.get("total") else total
            novos = [i for i in res["itens"] if i["identificador"] not in vistos]
            for i in novos:
                vistos.add(i["identificador"])
                itens.append(i)
            if res["total_linhas"] and not res["itens"]:
                avisos.append("linhas encontradas, mas nenhum identificador no padrão configurado")
                break
            if pag.get("rolagem"):
                self.alvo().evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(float(pag.get("pausa", 1.5)))
                if not novos and n > 1:
                    break
                continue
            if not pag.get("proximo") or (not novos and n > 1):
                break
            prox = self.alvo().locator(pag["proximo"]).first
            try:
                if prox.count() == 0 or not prox.is_visible() or prox.is_disabled():
                    break
                classe = (prox.get_attribute("class") or "") + " " + (prox.get_attribute("aria-disabled") or "")
                if re.search(r"disabled|inativ|true", classe):
                    break
                pb.clicar_leitura(prox, self.nav.log)
            except PermissionError:
                raise
            except Exception as exc:  # noqa: BLE001
                avisos.append(f"paginação interrompida: {exc}")
                break
            time.sleep(float(pag.get("pausa", 1.5)))
        else:
            avisos.append(f"teto de {teto_paginas} páginas atingido")
        return {"itens": itens, "total": total, "avisos": avisos}


def _escolhidas(todas: list, conf: dict) -> list:
    quer = pb.normalizar_lista(conf.get("pastas_tarefa"))
    if not quer:
        return todas
    nomes = {pb.slug(q["nome"]) for q in quer}
    return [p for p in todas if pb.slug(p["nome"]) in nomes]


def executar(args, amostra: bool) -> int:
    receita = carregar_receita()
    saida = Path(args.saida).expanduser() if args.saida else (
        pb.dir_dados() / "sondagem.json" if amostra else pb.arq_fila())
    with pb.Navegador(headless=getattr(args, "headless", False), log=dizer) as nav:
        motor = Motor(nav, receita)
        if not motor.entrar(args.espera_login):
            return 1
        todas = motor.pastas()
        dizer(f"{len(todas)} pasta(s) encontrada(s).")
        if amostra:
            res = {"ok": bool(todas), "sistema": (nav.conf.get("ferramenta") or {}).get("sistema"),
                   "pastas": [{"id": pb.slug(p["nome"]), "nome": p["nome"], "quantidade": p["quantidade"]}
                              for p in todas],
                   "campos": sorted((receita.get("lista") or {}).get("campos") or {}),
                   "baixar": False, "amostra": [], "avisos": []}
            if todas:
                motor.abrir_pasta(todas[0])
                pagina = motor.ler_pagina()
                res["amostra"] = pagina["itens"][:3]
                res["linhas_na_primeira_pagina"] = pagina["total_linhas"]
                if pagina["total_linhas"] and not pagina["itens"]:
                    res["avisos"].append("há linhas, mas nenhum identificador no padrão configurado")
            pb.gravar_json_atomico(saida, res)
            dizer(f"Sondagem gravada em {saida}")
            return 0 if res["ok"] else 1

        pastas, itens = [], []
        alvo = _escolhidas(todas, nav.conf)
        if not alvo:
            dizer("ERRO: nenhuma das pastas configuradas apareceu na ferramenta.")
            return 1
        for i, p in enumerate(alvo):
            pid = pb.slug(p["nome"])
            dizer(f"[{i + 1}/{len(alvo)}] {p['nome']}")
            if i:
                motor.voltar()
                atuais = {pb.slug(x["nome"]): x for x in motor.pastas()}
                p = atuais.get(pid, p)
            motor.abrir_pasta(p)
            lido = motor.ler_pasta()
            esperado = lido["total"] if lido["total"] is not None else p.get("quantidade")
            pastas.append({"id": pid, "nome": p["nome"], "esperado": esperado, "avisos": lido["avisos"]})
            itens += [{"identificador": it["identificador"], "pasta_id": pid, "campos": it["campos"]}
                      for it in lido["itens"]]
            dizer(f"    {len(lido['itens'])} lido(s)" + (f" de {esperado}" if esperado is not None else ""))
        f = nav.conf.get("ferramenta") or {}
        fila = pb.montar_fila(pastas, itens, ferramenta=" ".join(
            x for x in (f.get("sistema"), f.get("tribunal"), f.get("grau")) if x))
    pb.gravar_json_atomico(saida, fila)
    dizer(f"Fila gravada em {saida}: {fila['manifesto']['total_enumerado']} processo(s).")
    return pb.codigo_de_saida(fila)


def main() -> int:
    pb.utf8_no_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for nome in ("sondar", "listar"):
        s = sub.add_parser(nome)
        s.add_argument("--saida", default=None)
        s.add_argument("--espera-login", type=int, default=900)
        s.add_argument("--headless", action="store_true")
    args = ap.parse_args()
    return executar(args, amostra=args.cmd == "sondar")


if __name__ == "__main__":
    raise SystemExit(main())
