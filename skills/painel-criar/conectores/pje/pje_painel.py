"""
Acesso ao PJe (qualquer tribunal que use o painel do usuário interno) com Playwright — somente leitura.

Credenciais, perfil (localização), navegador e pastas vêm da configuração da
painel (módulo unidade.py ao lado). A sessão do navegador fica em
~/.projurista/painel/sessao/, restrita ao usuário.

O painel é Angular dentro do iframe `ngFrame`. Localizadores do Playwright não
funcionam nele (cross-origin): toda interação passa por `frame.evaluate`.
Seletores em ../referencias/seletores-pje.md.
"""

import html
import os
import re
import sys
import time
from pathlib import Path
from typing import Callable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import unidade as cfg_unidade  # noqa: E402

HOST_PJE = cfg_unidade.host()
BASE = cfg_unidade.base()
PAINEL_URL = f"{BASE}/ng2/dev.seam#/painel-usuario-interno"
MARCA_AUTOS_NG2 = "/ng2/dev.seam#/autos-digitais/"
HOST_SSO = cfg_unidade.pje()["sso"]


def base_do_grau(grau: int) -> str:
    return BASE  # o endereço da configuração já aponta para o grau do usuário


class PainelPJe:
    """Sessao de navegador no painel interno do PJe."""

    def __init__(self, headless: bool = False, perfil: Optional[str] = None,
                 destino: Optional[Path] = None, log: Optional[Callable] = None,
                 timeout: int = 60000, grau: int = 2):
        conf = cfg_unidade.pje()
        self.grau = int(grau)
        self.base = base_do_grau(self.grau)
        self.painel_url = f"{self.base}/ng2/dev.seam#/painel-usuario-interno"
        self.usuario, self.senha = cfg_unidade.credenciais()
        # Perfil = texto (ou trecho) da localização do usuário no PJe. Vazio:
        # mantém a localização em que o PJe abrir.
        self.perfil = (perfil if perfil is not None
                       else conf.get(f"perfil_{self.grau}g") or "").strip().lower()
        self.profile_dir = cfg_unidade.sessao_dir(self.grau)
        self.destino = Path(destino).expanduser() if destino else cfg_unidade.pasta_downloads()
        self.headless = headless
        self.timeout = timeout
        self.log = log or (lambda m: print(m))
        motor = (os.getenv("PJE_NAVEGADOR") or conf.get("navegador") or "chromium").strip().lower()
        self.motor = motor if motor in ("firefox", "chromium") else "chromium"

        self._pw = None
        self.navegador = None
        self.contexto = None
        self.pagina = None
        self.popup = None
        self._frame = None
        # Autos digitais: a interface antiga (JSF) fica na pagina principal do
        # popup; a nova (Angular, "ng2") fica dentro do iframe `ngFrame`.
        self.interface_ng2 = False
        self.frame_autos = None
        self._id_processo_href = None

    # ------------------------------------------------------------------ ciclo de vida

    def __enter__(self):
        self.iniciar()
        return self

    def __exit__(self, *_):
        self.fechar()
        return False

    def iniciar(self):
        from playwright.sync_api import sync_playwright

        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.destino.mkdir(parents=True, exist_ok=True)
        estado = self.profile_dir / "storage_state.json"

        self._pw = sync_playwright().start()
        self.log(f"Navegador: {self.motor}")
        self.navegador = getattr(self._pw, self.motor).launch(
            headless=self.headless, downloads_path=str(self.destino))

        args = {"accept_downloads": True, "viewport": {"width": 1920, "height": 1080}}
        if estado.exists():
            args["storage_state"] = str(estado)
            self.log(f"Sessão restaurada de {estado}")

        self.contexto = self.navegador.new_context(**args)
        self.pagina = self.contexto.new_page()
        self.pagina.set_default_timeout(self.timeout)

    def salvar_sessao(self):
        try:
            arq = self.profile_dir / "storage_state.json"
            self.contexto.storage_state(path=str(arq))
            cfg_unidade._restringir(arq)
        except Exception as exc:
            self.log(f"AVISO: não foi possível salvar a sessão: {exc}")

    def fechar(self):
        for fechar in (lambda: self.salvar_sessao(),
                       lambda: self.contexto and self.contexto.close(),
                       lambda: self.navegador and self.navegador.close(),
                       lambda: self._pw and self._pw.stop()):
            try:
                fechar()
            except Exception:
                pass

    # ------------------------------------------------------------------ login

    ESTADO_JS = r"""() => {
      const vis = (el) => !!el && (el.offsetParent !== null || el.getClientRects().length > 0);
      const txt = (document.body ? document.body.textContent || '' : '').toLowerCase();
      return {
        url: location.href,
        // Login antigo da própria aplicação (loginOld.seam): CPF + senha, sem 2º fator.
        form_local: vis(document.querySelector('#username'))
                    && vis(document.querySelector('#btnEntrar')),
        // Formulário do SSO (Keycloak): exige 2º fator.
        form_sso: vis(document.querySelector('#kc-login')),
        precisa_logar: txt.includes('você precisa estar logado')
                       || txt.includes('voce precisa estar logado'),
        tem_perfil: !!document.querySelector('select[id*="usuarioLocalizacao"]'),
        corpo: txt.length,
      };
    }"""

    def _estado(self) -> dict:
        try:
            return self.pagina.evaluate(self.ESTADO_JS)
        except Exception:
            return {"url": self.pagina.url, "form_local": False, "form_sso": False,
                    "precisa_logar": False, "tem_perfil": False, "corpo": 0}

    def login(self, espera_2fa: int = 900) -> bool:
        """Autentica no PJe.

        O PJe ora apresenta o login da própria aplicação (`loginOld.seam`, CPF
        e senha, sem segundo fator), ora o SSO, que exige segundo fator — nesse
        caso o código é digitado pelo usuário na janela do navegador.

        Nunca decida que a sessão está válida só porque a URL não é a do SSO: a
        tela de login local também não é, e confundir as duas faz o script
        prosseguir sem autenticação até quebrar em algum ponto adiante.
        """
        self.log(f"Acessando {self.base}")
        self.pagina.goto(self.base, timeout=60000, wait_until="domcontentloaded")
        try:
            self.pagina.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            time.sleep(3)

        estado = self._estado()
        if not (estado["form_local"] or estado["form_sso"] or estado["precisa_logar"]
                or HOST_SSO in estado["url"]):
            self.log("Sessão persistente válida — login não foi necessário.")
            return True

        if not (self.usuario and self.senha):
            return self._login_manual(espera_2fa)

        # ---------------------------------------------------------- login local
        if estado["form_local"] or estado["precisa_logar"]:
            self.log("Autenticando com CPF e senha (login da aplicação)...")
            try:
                if not estado["form_local"]:
                    self.pagina.goto(f"{self.base}/login.seam", timeout=60000,
                                     wait_until="domcontentloaded")
                    self.pagina.wait_for_selector("#username", timeout=30000)
                self.pagina.fill("#username", self.usuario)
                self.pagina.fill("#password", self.senha)
                self.pagina.click("#btnEntrar")
                try:
                    self.pagina.wait_for_load_state("networkidle", timeout=45000)
                except Exception:
                    time.sleep(6)
            except Exception as exc:
                self.log(f"ERRO ao preencher o formulário de login: {exc}")
                return False

            estado = self._estado()
            if estado["form_local"] or estado["precisa_logar"]:
                self.log("ERRO: o PJe continua exigindo login — verifique usuário e senha (/painel-criar).")
                return False
            self.log("Login concluído (CPF e senha).")
            self.salvar_sessao()
            return True

        # ------------------------------------------------------------ login SSO
        if self.headless:
            self.log("ERRO: caiu no SSO, que exige segundo fator. Execute sem --headless.")
            return False

        self.log("Fluxo do SSO detectado. Preenchendo credenciais...")
        try:
            self.pagina.bring_to_front()
        except Exception:
            pass
        try:
            self.pagina.wait_for_selector("#username", timeout=30000)
            self.pagina.fill("#username", self.usuario)
            self.pagina.fill("#password", self.senha)
            self.pagina.click("#kc-login")
        except Exception as exc:
            self.log(f"AVISO: preenchimento automático falhou ({exc}). Faça o login manual.")

        self.log(">>> Digite o código do segundo fator NA JANELA do navegador <<<")

        inicio, ciclo, logada = time.time(), 0, None
        while logada is None:
            decorrido = int(time.time() - inicio)
            if decorrido > espera_2fa:
                urls = [p.url[:100] for p in self.contexto.pages if p.url]
                self.log(f"ERRO: tempo esgotado ({espera_2fa}s) aguardando o segundo fator.")
                self.log(f"       abas: {urls}")
                return False
            for p in list(self.contexto.pages):
                try:
                    if (p.url or "").startswith("http") and HOST_SSO not in p.url:
                        logada = p
                        break
                except Exception:
                    continue
            if logada is None:
                ciclo += 1
                if ciclo % 6 == 1:
                    # Diagnóstico: sem isto, uma espera de 15 minutos termina
                    # sem que ninguém saiba o que a tela do SSO estava pedindo
                    # ou reclamando.
                    urls = [p.url[:90] for p in self.contexto.pages if p.url]
                    self.log(f"  aguardando... ({decorrido}s) abas: {urls}")
                    try:
                        tela = self.pagina.evaluate(
                            """() => {
                                const vis = el => el.offsetParent !== null
                                    || el.getClientRects().length > 0;
                                const erros = [...document.querySelectorAll(
                                    '.alert, .kc-feedback-text, [class*=error], .pf-c-alert__title')]
                                    .filter(vis).map(e => e.textContent.trim())
                                    .filter(Boolean).slice(0, 3);
                                const campos = [...document.querySelectorAll('input')]
                                    .filter(vis).filter(i => i.type !== 'hidden')
                                    .map(i => i.id || i.name || i.type).slice(0, 5);
                                return {erros, campos};
                            }""")
                        if tela.get("erros"):
                            self.log(f"    a página informa: {tela['erros']}")
                        if tela.get("campos"):
                            self.log(f"    campos aguardando preenchimento: {tela['campos']}")
                    except Exception:
                        pass
                else:
                    self.log(f"  aguardando... ({decorrido}s)")
                time.sleep(5)

        if logada is not self.pagina:
            self.pagina = logada
            self.pagina.set_default_timeout(self.timeout)
        time.sleep(5)

        self.log("Login concluído (SSO).")
        self.salvar_sessao()
        return True

    def _login_manual(self, espera: int) -> bool:
        """Sem credenciais guardadas (certificado, token ou opção do usuário): o login
        é feito por ele na janela; aqui só se espera a tela de login sumir."""
        if self.headless:
            self.log("ERRO: o PJe pede login. Execute sem --headless.")
            return False
        self.log(">>> Faça o login NA JANELA do navegador (senha, código ou certificado) <<<")
        inicio = time.time()
        while time.time() - inicio < espera:
            for p in list(self.contexto.pages):
                try:
                    self.pagina = p
                    e = self._estado()
                    if (e["url"].startswith(HOST_PJE) and HOST_SSO not in e["url"]
                            and not (e["form_local"] or e["form_sso"] or e["precisa_logar"])):
                        self.pagina.set_default_timeout(self.timeout)
                        self.log("Login concluído (manual).")
                        self.salvar_sessao()
                        return True
                except Exception:
                    continue
            time.sleep(4)
        self.log(f"ERRO: tempo esgotado ({espera}s) aguardando o login.")
        return False

    # ------------------------------------------------------------------ painel

    @property
    def frame(self):
        return self._frame or self.pagina

    CLICAR_MENU_PAINEL_JS = r"""() => {
      const norm = (s) => (s || '').trim().toLowerCase()
          .normalize('NFD').replace(/[\u0300-\u036f]/g, '');
      for (const el of document.querySelectorAll('a, span, li, button')) {
        const t = norm(el.textContent);
        if (t === 'painel do usuario' || (t.includes('painel do usuario') && t.length < 40)) {
          (el.closest('a, button, li') || el).click();
          return true;
        }
      }
      return false;
    }"""

    def _painel_carregado(self) -> dict:
        """Estado do iframe do painel: se já renderizou a lista de tarefas."""
        quadro = None
        for f in self.pagina.frames:
            if f.name == "ngFrame":
                quadro = f
        if not quadro:
            return {"pronto": False, "motivo": "iframe ngFrame ausente"}
        try:
            dados = quadro.evaluate(
                """() => ({
                    corpo: (document.body ? document.body.innerText || '' : '').length,
                    campos: document.querySelectorAll('#itNrProcesso').length,
                    texto: (document.body ? document.body.innerText || '' : '').toLowerCase(),
                })""")
        except Exception as exc:
            return {"pronto": False, "motivo": f"frame ilegível: {exc}"}
        return {
            "pronto": dados["campos"] > 0 or dados["corpo"] > 200,
            "campos": dados["campos"],
            "corpo": dados["corpo"],
            "sem_visibilidade": "sem visibilidade" in dados["texto"],
            "frame": quadro,
        }

    def abrir_painel(self, espera: int = 90) -> bool:
        """Abre o Painel do Usuário Interno pelo MENU.

        Navegar direto para a URL com o hash do painel não funciona: o iframe
        Angular fica vazio, porque o roteamento interno só é acionado pelo
        clique no menu. Verificado em 01/08/2026.
        """
        self.log("Abrindo o Painel do Usuário Interno...")
        # A URL com o hash sozinha deixa o iframe vazio, e o clique no menu
        # sozinho não basta: é a combinação que aciona o roteamento do Angular.
        self.pagina.goto(self.painel_url, timeout=60000, wait_until="domcontentloaded")
        try:
            self.pagina.wait_for_load_state("networkidle", timeout=30000)
        except Exception:
            time.sleep(5)
        try:
            self.pagina.wait_for_selector("iframe#ngFrame", timeout=30000)
        except Exception:
            self.log("AVISO: iframe ngFrame não apareceu.")
        time.sleep(5)

        inicio = time.time()
        estado = self._painel_carregado()
        tentativas_clique = 0
        while not estado.get("pronto") and time.time() - inicio < espera:
            if tentativas_clique < 4:
                try:
                    clicou = self.pagina.evaluate(self.CLICAR_MENU_PAINEL_JS)
                    tentativas_clique += 1
                    if clicou and tentativas_clique == 1:
                        self.log("  menu 'Painel do usuário' acionado")
                    elif not clicou and tentativas_clique == 1:
                        self.log("  AVISO: item de menu não encontrado; aguardando o Angular")
                except Exception as exc:
                    self.log(f"  AVISO: falha ao clicar no menu: {exc}")
            time.sleep(4)
            estado = self._painel_carregado()

        if not estado.get("pronto"):
            self.log(f"ERRO: o painel não carregou em {espera}s "
                     f"({estado.get('motivo', 'iframe vazio')}).")
            return False

        self._frame = estado["frame"]
        self.log(f"Painel carregado ({estado.get('campos')} campo(s) de processo).")
        if estado.get("sem_visibilidade"):
            self.log("AVISO: o painel indica usuário sem visibilidade — o perfil "
                     "pode não ser o da sua unidade.")
        return True

    PERFIS_JS = """() => {
        for (const s of document.querySelectorAll('select')) {
          if (!/usuarioLocalizacao/i.test(s.id || '')) continue;
          return {tem: true, atual: (s.options[s.selectedIndex] || {}).textContent || '',
                  opcoes: [...s.options].map(o => (o.textContent || '').trim()).filter(Boolean)};
        }
        return {tem: false, atual: '', opcoes: []};
    }"""

    def listar_perfis(self) -> dict:
        """Localizações que o PJe oferece ao usuário: {tem, atual, opcoes}."""
        try:
            r = self.pagina.evaluate(self.PERFIS_JS)
            r["atual"] = (r.get("atual") or "").strip()
            return r
        except Exception as exc:
            self.log(f"AVISO: não foi possível ler as localizações: {exc}")
            return {"tem": False, "atual": "", "opcoes": []}

    def selecionar_perfil(self, reabrir_painel: bool = True) -> bool:
        """Troca para a localização configurada. Não encontrada = erro (não segue em silêncio)."""
        if not self.perfil:
            atual = self.listar_perfis().get("atual")
            self.log(f"Perfil não configurado; usando a localização atual do PJe"
                     f"{': ' + atual if atual else ''}.")
            return True
        try:
            resultado = self.pagina.evaluate(
                """(alvo) => {
                    const sels = document.querySelectorAll('select');
                    for (const s of sels) {
                      if (!/usuarioLocalizacao/i.test(s.id || '')) continue;
                      const ops = [...s.options];
                      const o = ops.find(o => (o.textContent || '').trim().toLowerCase() === alvo)
                             || ops.find(o => (o.textContent || '').toLowerCase().includes(alvo));
                      if (!o) return {ok: false, motivo: 'nao_encontrado',
                                      opcoes: ops.map(o => (o.textContent || '').trim())};
                      if (s.value === o.value) return {ok: true, trocou: false,
                                                       texto: o.textContent.trim()};
                      s.value = o.value;
                      s.dispatchEvent(new Event('change', {bubbles: true}));
                      return {ok: true, trocou: true, texto: o.textContent.trim()};
                    }
                    return {ok: false, motivo: 'sem_seletor'};
                }""", self.perfil)
        except Exception as exc:
            self.log(f"ERRO: falha ao selecionar o perfil: {exc}")
            return False

        if not resultado.get("ok"):
            if resultado.get("motivo") == "sem_seletor":
                self.log("O PJe não mostrou seletor de localização (usuário com uma só); seguindo.")
                return True
            self.log(f"ERRO: a localização configurada (\"{self.perfil}\") não está entre as "
                     "oferecidas pelo PJe:")
            for o in resultado.get("opcoes", []):
                self.log(f"   - {o}")
            self.log("Rode /painel-criar para escolher de novo a localização.")
            return False

        self.log(f"Perfil: {resultado.get('texto')}")
        if resultado.get("trocou"):
            time.sleep(8)
            if reabrir_painel and self.grau == 2:
                self.abrir_painel()
        return True

    def buscar_processo(self, numero: str) -> bool:
        """Preenche o numero na coluna Tarefas e pesquisa.

        O campo precisa de InputEvent caractere a caractere: o Angular escuta o
        evento `input` e ignora atribuicao direta de `.value`.
        """
        self.log(f"Buscando o processo {numero}...")
        frame = self.frame

        try:
            frame.evaluate(
                """() => {
                    const alvos = document.querySelectorAll(
                      '[class*="dropdown"], details, [aria-haspopup], [data-toggle]');
                    for (const el of alvos) {
                      const t = (el.textContent || '').trim().toLowerCase();
                      if (t.includes('filtros') && t.length < 100) el.click();
                    }
                }""")
            time.sleep(2)
        except Exception:
            pass

        preenchido = frame.evaluate(
            """(numero) => {
                const inputs = document.querySelectorAll('#itNrProcesso');
                if (!inputs.length) return {ok: false, motivo: 'campo #itNrProcesso ausente'};
                const inp = inputs[inputs.length > 1 ? inputs.length - 1 : 0];
                inp.focus(); inp.click(); inp.value = '';
                inp.dispatchEvent(new InputEvent('input',
                  {bubbles: true, inputType: 'deleteContent'}));
                for (let i = 0; i < numero.length; i++) {
                  inp.value = numero.substring(0, i + 1);
                  inp.dispatchEvent(new InputEvent('input',
                    {bubbles: true, inputType: 'insertText', data: numero[i]}));
                }
                inp.dispatchEvent(new Event('change', {bubbles: true}));
                return {ok: true, valor: inp.value};
            }""", numero)

        if not preenchido.get("ok"):
            self.log(f"ERRO: {preenchido.get('motivo')}")
            return False
        time.sleep(1)

        clicado = frame.evaluate(
            """() => {
                const botoes = [];
                document.querySelectorAll('a, button, span').forEach(el => {
                  const t = (el.textContent || '').trim();
                  if (t === 'PESQUISAR' || t === 'Pesquisar') {
                    const r = el.getBoundingClientRect();
                    if (r.width > 0) botoes.push({el, x: r.x});
                  }
                });
                if (!botoes.length) return false;
                botoes.sort((a, b) => a.x - b.x);
                botoes[botoes.length - 1].el.click();
                return true;
            }""")
        if not clicado:
            self.log("ERRO: botão PESQUISAR não encontrado.")
            return False

        time.sleep(8)
        if self._processo_visivel(numero):
            self.log("Processo localizado na lista.")
            return True

        # O filtro reduz a coluna "Tarefas" às caixas que contêm o processo, mas
        # sem exibir o número: é preciso entrar na caixa para vê-lo.
        # Só elementos-folha: um contêiner pai também casa o padrão, mas clicar
        # nele não abre caixa nenhuma.
        caixas = frame.evaluate(
            """() => {
                const padrao = /\\[[A-Z0-9]{2,8}\\]\\s*\\d+\\s*$/;
                const brutos = [];
                for (const el of document.querySelectorAll('a, li, div, span')) {
                  const t = (el.textContent || '').trim().replace(/\\s+/g, ' ');
                  if (!t || t.length > 70) continue;
                  if (!padrao.test(t)) continue;
                  const r = el.getBoundingClientRect();
                  if (r.width <= 0 || r.height <= 0) continue;
                  brutos.push({el, t, x: Math.round(r.x), y: Math.round(r.y)});
                }
                // descarta quem tem descendente que também casa (fica só a folha)
                const folhas = brutos.filter(a =>
                  !brutos.some(b => b.el !== a.el && a.el.contains(b.el)));
                const vistos = new Set();
                const saida = [];
                for (const f of folhas) {
                  const chave = f.t + '@' + f.x + ',' + f.y;
                  if (vistos.has(chave)) continue;
                  vistos.add(chave);
                  saida.push({t: f.t, x: f.x, y: f.y});
                }
                return saida;
            }""")
        if caixas:
            direita = max(c["x"] for c in caixas)
            candidatas = [c for c in caixas if c["x"] >= direita - 60]
            self.log(f"  {len(candidatas)} caixa(s) na coluna Tarefas após o filtro: "
                     f"{[c['t'][:45] for c in candidatas[:6]]}")
            for caixa in candidatas[:8]:
                frame.evaluate(
                    """(args) => {
                        const [alvo, x, y] = args;
                        for (const el of document.querySelectorAll('a, li, div, span')) {
                          const t = (el.textContent || '').trim().replace(/\\s+/g, ' ');
                          if (t !== alvo) continue;
                          const r = el.getBoundingClientRect();
                          if (Math.abs(r.x - x) > 6 || Math.abs(r.y - y) > 6) continue;
                          (el.closest('a, li') || el).click();
                          return true;
                        }
                        return false;
                    }""", [caixa["t"], caixa["x"], caixa["y"]])
                time.sleep(7)
                if self._processo_visivel(numero):
                    self.log(f"Processo localizado na caixa: {caixa['t'][:60]}")
                    return True

        self.log("ERRO: processo não apareceu nas tarefas após o filtro. "
                 "Ele pode não estar em nenhuma caixa deste perfil.")
        return False

    def _processo_visivel(self, numero: str) -> bool:
        """O número aparece na página ou no iframe do painel."""
        alvo = re.sub(r"\D", "", numero)
        for origem in (self.pagina, self._frame):
            if not origem:
                continue
            try:
                texto = origem.text_content("body") or ""
            except Exception:
                continue
            if alvo and alvo in re.sub(r"\D", "", texto):
                return True
        return False

    def abrir_autos(self, numero: str) -> bool:
        """Abre os autos digitais do processo.

        Clique dentro do iframe cross-origin NÃO abre popup (bloqueio do
        navegador). O caminho que funciona é selecionar o processo, extrair o
        href de `listAutosDigitais.seam` e abrir a URL numa aba nova.
        """
        self.log("Abrindo os autos digitais...")
        frame = self.frame
        limpo = re.sub(r"\D", "", numero)

        selecionado = frame.evaluate(
            """(args) => {
                const [numero, limpo] = args;
                const casa = (el) => {
                  const t = (el.textContent || '').trim();
                  if (!t || t.length > 300) return false;
                  return t.includes(numero) || t.replace(/\\D/g, '').includes(limpo);
                };
                for (const el of document.querySelectorAll('a')) {
                  if (casa(el)) { el.click(); return {ok: true, tag: 'A'}; }
                }
                for (const el of document.querySelectorAll('div, span, tr, td, li')) {
                  if (casa(el)) { el.click(); return {ok: true, tag: el.tagName}; }
                }
                return {ok: false};
            }""", [numero, limpo])

        if not selecionado.get("ok"):
            self.log("ERRO: processo não localizado na lista para seleção.")
            return False
        time.sleep(6)

        href = frame.evaluate(
            """() => {
                for (const a of document.querySelectorAll('a')) {
                  const h = a.getAttribute('href') || '';
                  if (h.includes('listAutosDigitais') || h.includes('DetalheProcesso')) return h;
                }
                for (const a of document.querySelectorAll('a')) {
                  const h = a.getAttribute('href') || '';
                  if (h.includes('Processo/') && h.includes('seam')) return h;
                }
                return null;
            }""")

        if not href:
            self.log("ERRO: link dos autos digitais não encontrado no painel.")
            return False

        # O href vem do atributo com entidades HTML: sem desescapar, `&amp;`
        # transforma os parâmetros seguintes em `amp;chave=valor`.
        href = html.unescape(href)
        if href.startswith("/"):
            href = HOST_PJE + href
        elif not href.startswith("http"):
            href = f"{self.base}/{href.lstrip('/')}"
        self.log(f"  autos em {href[:110]}")

        # O idProcesso sai do proprio href, antes de qualquer redirecionamento:
        # na interface ng2 ele deixa a query e vai para o hash da URL.
        self.interface_ng2 = False
        self.frame_autos = None
        self._id_processo_href = None
        try:
            from urllib.parse import parse_qs, urlparse
            self._id_processo_href = parse_qs(urlparse(href).query).get("idProcesso", [None])[0]
        except Exception:
            pass

        try:
            self.popup = self.contexto.new_page()
            self.popup.set_default_timeout(self.timeout)
            self.popup.goto(href, timeout=90000, wait_until="domcontentloaded")
            try:
                self.popup.wait_for_load_state("networkidle", timeout=45000)
            except Exception:
                time.sleep(6)
        except Exception as exc:
            self.log(f"ERRO ao abrir a página dos autos: {exc}")
            return False

        self.log(f"Autos abertos: {self.popup.title()[:80]}")
        self._detectar_interface_autos()
        return True

    def abrir_autos_por_consulta(self, numero: str) -> bool:
        """Abre os autos pela Consulta Processual (usada no 1º grau, que não tem o
        painel de tarefas do assessor de 2º grau).

        Preenche os campos do número em `ConsultaProcesso/listView.seam`, pesquisa
        e clica no link do processo, que abre os autos digitais em nova aba.
        """
        m = re.match(r"(\d{7})-(\d{2})\.(\d{4})\.(\d)\.(\d{2})\.(\d{4})$", numero.strip())
        if not m:
            self.log(f"ERRO: número fora do padrão CNJ: {numero}")
            return False
        self.log("Abrindo a consulta processual...")
        try:
            self.pagina.goto(f"{self.base}/Processo/ConsultaProcesso/listView.seam",
                             timeout=60000, wait_until="domcontentloaded")
            try:
                self.pagina.wait_for_load_state("networkidle", timeout=20000)
            except Exception:
                time.sleep(3)
            campos = dict(zip(
                ("numeroSequencial", "numeroDigitoVerificador", "Ano", "ramoJustica",
                 "respectivoTribunal", "NumeroOrgaoJustica"), m.groups()))
            preenchidos = self.pagina.evaluate(
                """(campos) => {
                    let n = 0;
                    for (const [sufixo, valor] of Object.entries(campos)) {
                      const el = document.getElementById('fPP:numeroProcesso:' + sufixo);
                      if (!el) continue;
                      el.value = valor;
                      el.dispatchEvent(new Event('change', {bubbles: true}));
                      n++;
                    }
                    return n;
                }""", campos)
            if preenchidos < 6:
                self.log(f"ERRO: a tela de consulta não tem os campos esperados "
                         f"({preenchidos} de 6). O perfil pode não ter acesso à consulta "
                         "ou a interface mudou.")
                return False
            clicou = self.pagina.evaluate(
                """() => {
                    const b = document.getElementById('fPP:searchProcessos');
                    if (b) { b.click(); return true; }
                    for (const i of document.querySelectorAll('input[type=submit], input[type=button], button')) {
                      const t = (i.value || i.textContent || '').toLowerCase();
                      if (t.includes('pesquisar')) { i.click(); return true; }
                    }
                    return false;
                }""")
            if not clicou:
                self.log("ERRO: botão Pesquisar não encontrado na consulta.")
                return False
            time.sleep(5)
            try:
                self.pagina.wait_for_load_state("networkidle", timeout=20000)
            except Exception:
                time.sleep(3)

            link = None
            for a in self.pagina.locator("a").all():
                try:
                    if numero in (a.text_content() or ""):
                        link = a
                        break
                except Exception:
                    continue
            if link is None:
                corpo = self.pagina.text_content("body") or ""
                if numero in corpo:
                    self.log("ERRO: o processo apareceu no resultado, mas sem link para os autos "
                             "(sigilo ou falta de visibilidade para este perfil).")
                else:
                    self.log("ERRO: processo não encontrado na consulta do 1º grau.")
                return False

            self.interface_ng2 = False
            self.frame_autos = None
            self._id_processo_href = None
            with self.contexto.expect_page(timeout=120000) as nova:
                link.click()
            self.popup = nova.value
            self.popup.set_default_timeout(self.timeout)
            try:
                self.popup.wait_for_load_state("domcontentloaded", timeout=60000)
                self.popup.wait_for_load_state("networkidle", timeout=45000)
            except Exception:
                time.sleep(6)
        except Exception as exc:
            self.log(f"ERRO na consulta do processo: {exc}")
            return False

        self.log(f"Autos abertos: {self.popup.title()[:80]}")
        self._detectar_interface_autos()
        return True

    def _detectar_interface_autos(self, espera: int = 60) -> bool:
        """Identifica se os autos abriram na interface ng2 (Angular).

        Visto em 10/11/2026, primeiro em processo fisico migrado e, no mesmo
        dia, em agravo comum: `listAutosDigitais.seam`
        redireciona para `/ng2/dev.seam#/autos-digitais/<idProcesso>` e todo o
        conteudo passa a morar no iframe `ngFrame`. Os seletores da timeline
        JSF e o menu "Download autos do processo" nao existem nela.
        """
        if MARCA_AUTOS_NG2 not in (self.popup.url or ""):
            self.log("Interface dos autos: clássica (JSF).")
            return False

        self.interface_ng2 = True
        limite = time.time() + espera
        while time.time() < limite:
            for f in self.popup.frames:
                if f.name != "ngFrame":
                    continue
                try:
                    if f.evaluate("document.querySelectorAll('span.documento-nome').length") > 0:
                        self.frame_autos = f
                        self.log("Interface dos autos: ng2 (Angular, iframe ngFrame).")
                        return True
                except Exception:
                    pass
            time.sleep(2)

        # Sem pecas visiveis: guarda o frame mesmo assim, para que o chamador
        # registre "0 documentos" com a causa certa.
        for f in self.popup.frames:
            if f.name == "ngFrame":
                self.frame_autos = f
        self.log("Interface dos autos: ng2 (Angular), mas nenhuma peça apareceu no "
                 f"iframe em {espera}s.")
        return True

    def id_processo(self) -> Optional[str]:
        """Identificador interno do processo, necessario para a URL de download."""
        if not self.popup:
            return None
        if self._id_processo_href:
            return self._id_processo_href
        m = re.search(r"#/autos-digitais/(\d+)", self.popup.url or "")
        if m:
            return m.group(1)
        try:
            from urllib.parse import parse_qs, urlparse
            achado = parse_qs(urlparse(self.popup.url).query).get("idProcesso", [None])[0]
            if achado:
                return achado
        except Exception:
            pass
        try:
            html = self.popup.content()
            m = re.search(r"documento/download/[A-Za-z0-9]+/\w+/(\d+)/", html)
            if m:
                return m.group(1)
        except Exception:
            pass
        return None
