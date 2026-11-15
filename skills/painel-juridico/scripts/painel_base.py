#!/usr/bin/env python3
"""
Base comum do Painel Jurídico: configuração, credenciais, navegador e formato da fila.

Tudo o que é do usuário fica em ~/.projurista/painel/ (ou em PROJURISTA_PAINEL_DIR),
com permissão restrita:

    config.json         respostas da entrevista (/painel-criar)
    conector/           script que lê a ferramenta do usuário
    sessao/             sessão do navegador (cookies)
    dados/              fila, logs e registros de tarefas
    reconhecimento/     retratos temporários das telas (apagados ao final)

Uso pela linha de comando:

    python painel_base.py mostrar            resumo legível da configuração
    python painel_base.py json               configuração inteira (sem senha)
    python painel_base.py definir chave=valor [chave=valor ...]
    python painel_base.py credenciais        pergunta usuário e senha (sem eco)
    python painel_base.py conferir           lista o que falta configurar
"""
import getpass
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional, Tuple

VERSAO = 1
SERVICO_COFRE = "projurista-painel"
PORTA_PADRAO = 8770
REGEX_CNJ = r"\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}"

FASES_PADRAO = [
    {"id": "baixado", "nome": "Baixado"},
    {"id": "elaboracao", "nome": "Em elaboração"},
    {"id": "conferencia", "nome": "Aguardando conferência"},
    {"id": "conferido", "nome": "Conferido"},
]

# Palavras que indicam ação de escrita na ferramenta. O painel só lê: nenhum
# conector pode clicar em elemento cujo texto contenha uma delas.
ACOES_PROIBIDAS = (
    "assinar", "assinatura", "enviar", "remeter", "movimentar", "encaminhar",
    "salvar", "gravar", "excluir", "remover", "apagar", "deletar", "juntar",
    "protocolar", "peticionar", "confirmar", "finalizar", "concluir", "lançar",
    "lancar", "registrar voto", "votar", "publicar", "intimar", "citar",
    "redistribuir", "arquivar", "baixar definitivamente", "homologar",
    "transitar", "minutar", "elaborar", "incluir", "alterar", "editar",
)


# --------------------------------------------------------------------- pastas

def dir_painel() -> Path:
    bruto = os.environ.get("PROJURISTA_PAINEL_DIR")
    return Path(bruto).expanduser() if bruto else Path.home() / ".projurista" / "painel"


def dir_claude() -> Path:
    bruto = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(bruto).expanduser() if bruto else Path.home() / ".claude"


def restringir(caminho: Path) -> None:
    """Deixa o arquivo ou a pasta acessível só ao dono (sem efeito no Windows)."""
    try:
        if caminho.is_dir():
            os.chmod(caminho, stat.S_IRWXU)
        else:
            os.chmod(caminho, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def _pasta_restrita(nome: str) -> Path:
    raiz = dir_painel()
    if not raiz.exists():
        raiz.mkdir(parents=True, exist_ok=True)
        restringir(raiz)
    p = raiz / nome
    if not p.exists():
        p.mkdir(parents=True, exist_ok=True)
        restringir(p)
    return p


def dir_dados() -> Path:
    return _pasta_restrita("dados")


def dir_sessao() -> Path:
    return _pasta_restrita("sessao")


def dir_conector() -> Path:
    return _pasta_restrita("conector")


def dir_reconhecimento() -> Path:
    return _pasta_restrita("reconhecimento")


def arq_config() -> Path:
    return dir_painel() / "config.json"


def arq_fila() -> Path:
    return dir_dados() / "fila.json"


def utf8_no_console() -> None:
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


# --------------------------------------------------------------- configuração

def config_vazia() -> dict:
    return {
        "versao": VERSAO,
        "ferramenta": {"sistema": "", "tribunal": "", "grau": "", "url": "",
                       "login": "", "navegador": "chromium", "usuario": "",
                       "perfil": ""},
        "identificador": {"rotulo": "Número do processo", "regex": REGEX_CNJ},
        "pastas_tarefa": [],
        "campos_cartao": ["classe", "assunto", "partes"],
        "fases": [dict(f) for f in FASES_PADRAO],
        "pecas": [],
        "referencias": {"mcps": [], "precedentes": [], "modelos": [], "observacoes": ""},
        "pastas": {"processos": ""},
        "conector": {"arquivo": "", "baixar": False},
        "porta": PORTA_PADRAO,
    }


def _mesclar(base: dict, novo: dict) -> dict:
    for chave, valor in (novo or {}).items():
        if isinstance(valor, dict) and isinstance(base.get(chave), dict):
            _mesclar(base[chave], valor)
        else:
            base[chave] = valor
    return base


def carregar() -> dict:
    conf = config_vazia()
    arq = arq_config()
    if arq.is_file():
        try:
            _mesclar(conf, json.loads(arq.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            raise SystemExit(f"Configuração ilegível em {arq}: {exc}")
    return conf


def gravar_json_atomico(caminho: Path, dados, restrito: bool = True) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(caminho.parent), prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
        os.replace(tmp, caminho)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    if restrito:
        restringir(caminho)


def gravar(conf: dict) -> None:
    dir_dados()  # garante a raiz restrita
    conf["atualizado_em"] = datetime.now().isoformat(timespec="seconds")
    gravar_json_atomico(arq_config(), conf)


def definir(pares: List[str]) -> dict:
    """Aplica 'a.b=valor'. Valor em JSON quando começar por [, {, ", número, true/false."""
    conf = carregar()
    for par in pares:
        if "=" not in par:
            raise SystemExit(f"Use chave=valor (recebido: {par!r}).")
        chave, bruto = par.split("=", 1)
        try:
            valor = json.loads(bruto)
        except ValueError:
            valor = bruto
        no = conf
        partes = chave.strip().split(".")
        for p in partes[:-1]:
            if not isinstance(no.get(p), dict):
                no[p] = {}
            no = no[p]
        no[partes[-1]] = valor
    validar(conf, estrito=False)
    gravar(conf)
    return conf


def slug(texto: str) -> str:
    import unicodedata
    base = unicodedata.normalize("NFD", str(texto))
    base = "".join(c for c in base if unicodedata.category(c) != "Mn").lower()
    return re.sub(r"[^a-z0-9]+", "-", base).strip("-") or "item"


def normalizar_lista(lista, extras: Tuple[str, ...] = ()) -> List[dict]:
    """Aceita nomes soltos ou dicionários; devolve [{id, nome, ...}] sem ids repetidos."""
    saida, vistos = [], set()
    for item in lista or []:
        d = {"nome": item} if isinstance(item, str) else dict(item or {})
        nome = str(d.get("nome") or "").strip()
        if not nome:
            continue
        ident = str(d.get("id") or slug(nome))
        while ident in vistos:
            ident += "-2"
        vistos.add(ident)
        novo = {"id": ident, "nome": nome}
        for e in extras:
            if d.get(e) not in (None, ""):
                novo[e] = d[e]
        saida.append(novo)
    return saida


def fases(conf: Optional[dict] = None) -> List[dict]:
    conf = conf or carregar()
    lista = normalizar_lista(conf.get("fases"))
    return lista if len(lista) >= 2 else [dict(f) for f in FASES_PADRAO]


def pecas(conf: Optional[dict] = None) -> List[dict]:
    """Peças que o usuário produz: {id, nome, arquivo, fase}."""
    conf = conf or carregar()
    ids_fase = [f["id"] for f in fases(conf)]
    saida = []
    for p in normalizar_lista(conf.get("pecas"), extras=("arquivo", "fase")):
        p["arquivo"] = Path(str(p.get("arquivo") or f"{p['id']}.txt")).name
        if p.get("fase") not in ids_fase:
            # sem indicação, a peça pronta leva o processo à penúltima fase
            p["fase"] = ids_fase[-2] if len(ids_fase) >= 2 else ids_fase[0]
        saida.append(p)
    return saida


def regex_identificador(conf: Optional[dict] = None):
    conf = conf or carregar()
    bruto = (conf.get("identificador") or {}).get("regex") or REGEX_CNJ
    try:
        return re.compile(bruto)
    except re.error as exc:
        raise SystemExit(f"Padrão do identificador inválido ({bruto!r}): {exc}")


def pasta_processos(conf: Optional[dict] = None) -> Path:
    conf = conf or carregar()
    bruto = (conf.get("pastas") or {}).get("processos") or "~/Processos-Painel"
    return Path(bruto).expanduser()


def nome_de_pasta(identificador: str) -> str:
    """Nome de pasta seguro para um identificador (troca barras e caracteres inválidos)."""
    return re.sub(r'[\\/:*?"<>|]+', "-", str(identificador)).strip(" .") or "processo"


def faltando(conf: Optional[dict] = None) -> List[str]:
    conf = conf or carregar()
    f = conf.get("ferramenta") or {}
    falta = []
    if not f.get("sistema"):
        falta.append("ferramenta.sistema")
    if not f.get("url"):
        falta.append("ferramenta.url")
    if not (conf.get("conector") or {}).get("arquivo"):
        falta.append("conector.arquivo")
    if not (conf.get("pastas") or {}).get("processos"):
        falta.append("pastas.processos")
    if not conf.get("pecas"):
        falta.append("pecas")
    return falta


def validar(conf: dict, estrito: bool = True) -> List[str]:
    erros = []
    url = (conf.get("ferramenta") or {}).get("url") or ""
    if url and not re.match(r"^https?://", url):
        erros.append("ferramenta.url precisa começar por http:// ou https://")
    try:
        re.compile((conf.get("identificador") or {}).get("regex") or REGEX_CNJ)
    except re.error as exc:
        erros.append(f"identificador.regex inválido: {exc}")
    try:
        porta = int(conf.get("porta") or PORTA_PADRAO)
        if not 1024 <= porta <= 65535:
            erros.append("porta deve ficar entre 1024 e 65535")
    except (TypeError, ValueError):
        erros.append("porta deve ser um número")
    if erros and not estrito:
        raise SystemExit("Configuração recusada: " + "; ".join(erros))
    return erros


def caminho_conector(conf: Optional[dict] = None) -> Optional[Path]:
    conf = conf or carregar()
    bruto = (conf.get("conector") or {}).get("arquivo") or ""
    if not bruto:
        return None
    p = Path(bruto).expanduser()
    if not p.is_absolute():
        p = dir_conector() / p
    return p


# ---------------------------------------------------------------- credenciais

def _keyring():
    try:
        import keyring  # type: ignore
        keyring.get_keyring()
        return keyring
    except Exception:
        return None


def credenciais() -> Tuple[str, str]:
    """(usuário, senha). Senha vem do cofre de senhas do sistema ou do arquivo restrito."""
    conf = carregar()
    usuario = (conf.get("ferramenta") or {}).get("usuario") or ""
    senha = ""
    kr = _keyring()
    if kr and usuario:
        try:
            senha = kr.get_password(SERVICO_COFRE, usuario) or ""
        except Exception:
            senha = ""
    if not senha:
        arq = dir_painel() / "acesso.env"
        if arq.is_file():
            for linha in arq.read_text(encoding="utf-8").splitlines():
                if linha.startswith("SENHA="):
                    senha = linha.split("=", 1)[1]
    return usuario, senha


def gravar_credenciais(usuario: str, senha: str) -> str:
    conf = carregar()
    conf.setdefault("ferramenta", {})["usuario"] = usuario
    gravar(conf)
    kr = _keyring()
    if kr:
        try:
            kr.set_password(SERVICO_COFRE, usuario, senha)
            arq = dir_painel() / "acesso.env"
            if arq.exists():
                arq.unlink()
            return "cofre de senhas do sistema"
        except Exception:
            pass
    arq = dir_painel() / "acesso.env"
    arq.write_text(f"SENHA={senha}\n", encoding="utf-8")
    restringir(arq)
    return f"arquivo restrito {arq}"


def perguntar_credenciais() -> int:
    if not sys.stdin.isatty():
        print("Rode este comando você mesmo, no terminal: a senha é digitada sem aparecer "
              "e não passa pela conversa.")
        return 1
    usuario = input("Usuário de acesso (CPF, login ou matrícula): ").strip()
    senha = getpass.getpass("Senha (não aparece ao digitar): ")
    if not usuario or not senha:
        print("Usuário e senha são obrigatórios.")
        return 1
    onde = gravar_credenciais(usuario, senha)
    print(f"Credenciais guardadas no {onde}.")
    return 0


# ------------------------------------------------------------------- ambiente

def python_do_pacote() -> Optional[Path]:
    venv = dir_painel().parent / "venv"
    for rel in ("bin/python", "bin/python3", "Scripts/python.exe"):
        p = venv / rel
        if p.is_file():
            return p
    return None


def garantir_ambiente(*modulos: str) -> None:
    """Se faltar módulo e existir o ambiente do pacote, reexecuta o script nele."""
    import importlib.util
    falta = [m for m in modulos if importlib.util.find_spec(m) is None]
    if not falta:
        return
    alvo = python_do_pacote()
    if (alvo and os.environ.get("PROJURISTA_SEM_REEXEC") != "1"
            and os.path.abspath(str(alvo)) != os.path.abspath(sys.executable)):
        env = dict(os.environ, PROJURISTA_SEM_REEXEC="1")
        raise SystemExit(subprocess.call([str(alvo)] + sys.argv, env=env))
    raise SystemExit("Faltam dependências (" + ", ".join(falta) + "). Rode o instalador do "
                     "pacote: python instalar.py --dependencias")


# ------------------------------------------------------------------ navegador

class Navegador:
    """Navegador do Playwright com sessão guardada. Uso:

        with Navegador() as nav:
            nav.abrir()                      # vai ao endereço da configuração
            nav.esperar_login(lambda p: p.locator("#menu").count() > 0)
            ...
    """

    def __init__(self, headless: bool = False, log: Optional[Callable] = None,
                 timeout: int = 60000):
        garantir_ambiente("playwright")
        self.conf = carregar()
        f = self.conf.get("ferramenta") or {}
        self.url = f.get("url") or ""
        motor = (os.getenv("PAINEL_NAVEGADOR") or f.get("navegador") or "chromium").lower()
        self.motor = motor if motor in ("chromium", "firefox", "chrome", "msedge") else "chromium"
        self.headless = headless or os.environ.get("PAINEL_HEADLESS") == "1"
        self.timeout = timeout
        self.log = log or print
        self._pw = self.navegador = self.contexto = self.pagina = None
        self._estado = dir_sessao() / "storage_state.json"

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        if self.motor == "firefox":
            self.navegador = self._pw.firefox.launch(headless=self.headless)
        elif self.motor in ("chrome", "msedge"):
            # navegador instalado no sistema: necessário para certificado digital
            self.navegador = self._pw.chromium.launch(headless=self.headless, channel=self.motor)
        else:
            self.navegador = self._pw.chromium.launch(headless=self.headless)
        opcoes = {"accept_downloads": True, "locale": "pt-BR"}
        if self._estado.is_file():
            opcoes["storage_state"] = str(self._estado)
        self.contexto = self.navegador.new_context(**opcoes)
        self.pagina = self.contexto.new_page()
        self.pagina.set_default_timeout(self.timeout)
        return self

    def __exit__(self, *_):
        self.salvar_sessao()
        for alvo in (self.contexto, self.navegador):
            try:
                alvo and alvo.close()
            except Exception:
                pass
        try:
            self._pw and self._pw.stop()
        except Exception:
            pass

    def salvar_sessao(self) -> None:
        try:
            self.contexto.storage_state(path=str(self._estado))
            restringir(self._estado)
        except Exception:
            pass

    def esquecer_sessao(self) -> None:
        try:
            self._estado.unlink()
        except OSError:
            pass

    def abrir(self, url: Optional[str] = None) -> None:
        alvo = url or self.url
        if not alvo:
            raise SystemExit("Endereço da ferramenta não configurado. Rode /painel-criar.")
        self.log(f"Acessando {alvo}")
        self.pagina.goto(alvo, wait_until="domcontentloaded")
        try:
            self.pagina.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

    def esperar_login(self, logado: Callable, espera: int = 900,
                      preencher: Optional[Callable] = None) -> bool:
        """Espera até `logado(pagina)` ser verdadeiro.

        `preencher(pagina, usuario, senha)` é chamado uma vez, se houver credenciais
        guardadas. Segundo fator, certificado e captcha são sempre do usuário, na janela.
        """
        import time

        def _ok() -> bool:
            for p in list(self.contexto.pages):
                try:
                    if logado(p):
                        self.pagina = p
                        return True
                except Exception:
                    continue
            return False

        if _ok():
            self.log("Sessão guardada ainda válida: login não foi necessário.")
            return True
        usuario, senha = credenciais()
        tentou = False
        if preencher and usuario and senha:
            try:
                preencher(self.pagina, usuario, senha)
                tentou = True
            except Exception as exc:
                self.log(f"AVISO: não preenchi o login sozinho ({exc}). Faça-o na janela.")
        if self.headless:
            # sem janela não há como digitar código ou escolher certificado
            if not tentou:
                self.log("ERRO: a ferramenta pede login. Rode sem --headless.")
                return False
            espera = min(espera, 30)
        else:
            self.log(">>> Conclua o login NA JANELA do navegador (senha, código ou certificado) <<<")
        inicio = time.time()
        while time.time() - inicio < espera:
            if _ok():
                self.log("Login concluído.")
                self.salvar_sessao()
                return True
            time.sleep(3)
        self.log(f"ERRO: tempo esgotado ({espera}s) aguardando o login.")
        return False


def texto_proibido(texto: str) -> bool:
    t = slug(texto or "").replace("-", " ")
    return any(slug(p).replace("-", " ") in t for p in ACOES_PROIBIDAS)


def clicar_leitura(localizador, log: Optional[Callable] = None, pasta: bool = False) -> None:
    """Clica somente se o elemento não indicar ação de escrita na ferramenta.

    pasta=True: o elemento é o link de uma pasta de tarefa. O nome da pasta pode conter
    verbos como "Minutar" ou "Assinar" (é o nome da tarefa, não uma ação); nesse caso a
    trava passa a ser estrutural: recusa-se o que enviaria um formulário.
    """
    try:
        info = localizador.evaluate(
            """el => ({tag: el.tagName.toLowerCase(), tipo: (el.getAttribute('type') || '').toLowerCase(),
                      em_form: !!el.closest('form'),
                      rotulo: [(el.innerText || el.textContent || ''), el.getAttribute('title') || '',
                               el.getAttribute('aria-label') || '', el.getAttribute('value') || ''].join(' ')})""",
            timeout=5000)
    except Exception as exc:
        raise PermissionError(f"Clique recusado: não consegui examinar o elemento ({exc}).")
    rotulo = " ".join((info.get("rotulo") or "").split())
    envia = info["em_form"] and (info["tag"] == "button" and info["tipo"] in ("", "submit")
                                 or info["tag"] == "input" and info["tipo"] in ("submit", "image"))
    if envia:
        raise PermissionError(f"Clique recusado: '{rotulo[:60]}' envia um formulário. "
                              "O painel só lê a ferramenta.")
    if not pasta and texto_proibido(rotulo):
        raise PermissionError(f"Clique recusado: '{rotulo[:60]}' parece ação de "
                              "escrita. O painel só lê a ferramenta.")
    localizador.click()


# ----------------------------------------------------------------------- fila

def montar_fila(pastas: List[dict], itens: List[dict], ferramenta: str = "",
                avisos: Optional[List[str]] = None) -> dict:
    """Monta a fila no formato do contrato (veja docs/contrato-conector.md).

    pastas: [{id, nome, esperado (int ou None), avisos?}]
    itens:  [{identificador, pasta_id, campos: {...}}]
    """
    por_pasta = {}
    vistos, limpos = set(), []
    for it in itens:
        ident = str(it.get("identificador") or "").strip()
        if not ident:
            continue
        pid = str(it.get("pasta_id") or "")
        chave = (ident, pid)
        if chave in vistos:
            continue
        vistos.add(chave)
        por_pasta[pid] = por_pasta.get(pid, 0) + 1
        limpos.append({"identificador": ident, "pasta_id": pid,
                       "campos": dict(it.get("campos") or {})})
    saida_pastas = []
    total_esp, tudo_ok = 0, True
    for p in pastas:
        pid = str(p.get("id") or slug(p.get("nome", "")))
        esperado = p.get("esperado")
        enumerados = por_pasta.get(pid, 0)
        completo = esperado is None or enumerados >= int(esperado)
        tudo_ok = tudo_ok and completo
        total_esp += int(esperado) if esperado is not None else enumerados
        saida_pastas.append({"id": pid, "nome": p.get("nome") or pid,
                             "esperado": esperado, "enumerados": enumerados,
                             "completo": completo, "avisos": list(p.get("avisos") or [])})
    return {
        "versao": VERSAO,
        "gerada_em": datetime.now().isoformat(timespec="seconds"),
        "ferramenta": ferramenta,
        "pastas": saida_pastas,
        "itens": limpos,
        "manifesto": {"completo": tudo_ok, "total_esperado": total_esp,
                      "total_enumerado": len(limpos), "avisos": list(avisos or [])},
    }


def validar_fila(fila: dict) -> List[str]:
    erros = []
    if not isinstance(fila, dict):
        return ["a fila não é um objeto JSON"]
    for chave in ("pastas", "itens", "manifesto"):
        if chave not in fila:
            erros.append(f"falta a chave '{chave}'")
    if erros:
        return erros
    ids = set()
    for i, p in enumerate(fila["pastas"]):
        if not p.get("id") or not p.get("nome"):
            erros.append(f"pastas[{i}] sem id ou nome")
        ids.add(str(p.get("id")))
        for chave in ("enumerados", "completo"):
            if chave not in p:
                erros.append(f"pastas[{i}] sem '{chave}'")
    for i, it in enumerate(fila["itens"]):
        if not it.get("identificador"):
            erros.append(f"itens[{i}] sem identificador")
        if str(it.get("pasta_id")) not in ids:
            erros.append(f"itens[{i}] aponta para pasta desconhecida ({it.get('pasta_id')!r})")
        if not isinstance(it.get("campos", {}), dict):
            erros.append(f"itens[{i}].campos deve ser um objeto")
        if len(erros) > 20:
            erros.append("... (demais erros omitidos)")
            break
    if "completo" not in (fila.get("manifesto") or {}):
        erros.append("manifesto sem 'completo'")
    return erros


def codigo_de_saida(fila: dict) -> int:
    return 0 if (fila.get("manifesto") or {}).get("completo") else 2


# ------------------------------------------------------------------------ CLI

def texto_resumo(conf: dict) -> str:
    f = conf.get("ferramenta") or {}
    ref = conf.get("referencias") or {}
    linhas = [
        f"Ferramenta: {f.get('sistema') or '(não informada)'}"
        + (f" — {f.get('tribunal')}" if f.get("tribunal") else "")
        + (f", {f.get('grau')}" if f.get("grau") else ""),
        f"Endereço: {f.get('url') or '(não informado)'}",
        f"Login: {f.get('login') or '(não informado)'} | navegador: {f.get('navegador')}"
        + (" | usuário guardado" if f.get("usuario") else ""),
        f"Perfil ou lotação: {f.get('perfil') or '(o que a ferramenta abrir)'}",
        "Pastas de tarefa: " + (", ".join(p["nome"] for p in normalizar_lista(conf.get("pastas_tarefa")))
                                or "(todas as que o perfil enxergar)"),
        "Campos do cartão: " + ", ".join(conf.get("campos_cartao") or []),
        "Fases: " + " → ".join(x["nome"] for x in fases(conf)),
        "Peças: " + (", ".join(f"{p['nome']} ({p['arquivo']})" for p in pecas(conf)) or "(nenhuma)"),
        f"Pasta dos processos: {pasta_processos(conf)}",
        f"Conector: {caminho_conector(conf) or '(não definido)'}"
        + (" (com download)" if (conf.get('conector') or {}).get('baixar') else ""),
        "MCPs: " + (", ".join(ref.get("mcps") or []) or "(nenhum informado)"),
        "Precedentes: " + (" | ".join(_descrever(x) for x in ref.get("precedentes") or []) or "(não informado)"),
        "Modelos: " + (" | ".join(_descrever(x) for x in ref.get("modelos") or []) or "(não informado)"),
        f"Porta do painel: {conf.get('porta')}",
    ]
    falta = faltando(conf)
    if falta:
        linhas.append("FALTA CONFIGURAR: " + ", ".join(falta) + " — rode /painel-criar.")
    return "\n".join(linhas)


def _descrever(fonte) -> str:
    if isinstance(fonte, str):
        return fonte
    partes = [str(fonte.get(k)) for k in ("tipo", "onde", "como") if fonte.get(k)]
    return " — ".join(partes)


def main() -> int:
    utf8_no_console()
    args = sys.argv[1:]
    cmd = args[0] if args else "mostrar"
    if cmd == "mostrar":
        print(texto_resumo(carregar()))
    elif cmd == "json":
        print(json.dumps(carregar(), ensure_ascii=False, indent=2))
    elif cmd == "definir":
        definir(args[1:])
        print(texto_resumo(carregar()))
    elif cmd == "credenciais":
        return perguntar_credenciais()
    elif cmd == "conferir":
        falta = faltando()
        print("Tudo configurado." if not falta else "Falta: " + ", ".join(falta))
        return 1 if falta else 0
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
