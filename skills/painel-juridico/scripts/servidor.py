#!/usr/bin/env python3
"""
Servidor local do Painel Jurídico. Só biblioteca padrão; escuta apenas em 127.0.0.1.

    python servidor.py abrir      sobe em segundo plano (se preciso) e abre o navegador
    python servidor.py parar
    python servidor.py status
    python servidor.py servir     roda em primeiro plano (uso interno e testes)

Opções de `servir`: --porta N, --sem-terminal (não abre o terminal em "Processar agora").
"""
import argparse
import hashlib
import json
import os
import platform
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
import painel_base as pb  # noqa: E402
import nucleo  # noqa: E402

ESTATICO = AQUI.parent / "static" / "index.html"
TTL_CACHE = 3.0
LIMITE_CORPO = 1_000_000
TIMEOUT_LISTAR = int(os.environ.get("PAINEL_TIMEOUT_LISTAR", "1800"))
TIMEOUT_BAIXAR = int(os.environ.get("PAINEL_TIMEOUT_BAIXAR", "1800"))
COMANDO_PROCESSAR = "/painel-juridico processar"
WINDOWS = platform.system() == "Windows"
MAC = platform.system() == "Darwin"


def arq_pid() -> Path:
    return pb.dir_dados() / "servidor.pid"


def dir_jobs() -> Path:
    d = pb.dir_dados() / "jobs"
    d.mkdir(parents=True, exist_ok=True)
    return d


# --------------------------------------------------------------------- sistema

def abrir_pasta(caminho: Path) -> None:
    if WINDOWS:
        os.startfile(str(caminho))  # type: ignore[attr-defined]
    elif MAC:
        subprocess.Popen(["open", str(caminho)])
    else:
        subprocess.Popen(["xdg-open", str(caminho)])


def para_lixeira(caminho: Path) -> None:
    """Envia a pasta à Lixeira do sistema (recuperável). Nunca apaga em definitivo."""
    try:
        from send2trash import send2trash  # type: ignore
        send2trash(str(caminho))
        return
    except ImportError:
        pass
    if MAC:
        script = 'tell application "Finder" to delete (POSIX file "%s" as alias)' % \
            str(caminho).replace("\\", "\\\\").replace('"', '\\"')
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip() or "o Finder recusou")
        return
    raise RuntimeError("Lixeira indisponível: instale o pacote send2trash (python instalar.py --dependencias).")


def abrir_terminal(comando_claude: str = COMANDO_PROCESSAR) -> dict:
    """Abre uma sessão interativa do Claude Code já com o comando do painel."""
    claude = shutil.which("claude")
    if not claude:
        for c in (Path.home() / ".local/bin/claude", Path("/opt/homebrew/bin/claude"),
                  Path("/usr/local/bin/claude")):
            if c.is_file():
                claude = str(c)
                break
    manual = f'claude "{comando_claude}"'
    if os.environ.get("PAINEL_SEM_TERMINAL") == "1":
        return {"ok": True, "simulado": True, "comando": manual}
    if not claude:
        return {"ok": False, "comando": manual,
                "erro": "Não encontrei o Claude Code no computador. Abra o terminal e rode o comando."}
    try:
        if MAC:
            linha = f'cd "$HOME" && "{claude}" "{comando_claude}"'
            script = ('tell application "Terminal"\nactivate\ndo script "%s"\nend tell'
                      % linha.replace("\\", "\\\\").replace('"', '\\"'))
            subprocess.run(["osascript", "-e", script], check=True, capture_output=True, timeout=30)
        elif WINDOWS:
            wt = shutil.which("wt")
            if wt:
                subprocess.Popen([wt, "-d", str(Path.home()), "cmd", "/k", claude, comando_claude])
            else:
                subprocess.Popen(["cmd", "/c", "start", "Painel Jurídico", "cmd", "/k", claude,
                                  comando_claude], cwd=str(Path.home()))
        else:
            for term, flag in (("x-terminal-emulator", "-e"), ("gnome-terminal", "--"),
                               ("konsole", "-e"), ("xterm", "-e")):
                if shutil.which(term):
                    subprocess.Popen([term, flag, claude, comando_claude], cwd=str(Path.home()))
                    break
            else:
                return {"ok": False, "comando": manual, "erro": "Nenhum terminal conhecido encontrado."}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "comando": manual, "erro": f"Não consegui abrir o terminal: {exc}"}
    return {"ok": True, "comando": manual}


def matar_arvore(proc: subprocess.Popen) -> None:
    try:
        if WINDOWS:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass


# ---------------------------------------------------------------------- estado

class Estado:
    def __init__(self):
        self._trava = threading.Lock()
        self._cache = None
        self._em = 0.0

    def invalidar(self) -> None:
        with self._trava:
            self._cache = None

    def obter(self, forcar: bool = False) -> dict:
        with self._trava:
            if not forcar and self._cache is not None and time.time() - self._em < TTL_CACHE:
                return self._cache
            self._cache = nucleo.varrer()
            self._em = time.time()
            return self._cache

    @staticmethod
    def resolver_pasta(texto: str) -> Path:
        if not texto:
            raise ValueError("pasta não informada")
        return nucleo.resolver_pasta(str(texto))


# ------------------------------------------------------------------------ jobs

class Job:
    def __init__(self, tipo: str, alvo: str = ""):
        self.id = uuid.uuid4().hex[:10]
        self.tipo, self.alvo = tipo, alvo
        self.status = "aguardando"      # aguardando | executando | concluido | parcial | falhou | cancelado
        self.codigo = None
        self.criado_em = time.time()
        self.inicio = self.fim = None
        self.mensagem = ""
        self.log = dir_jobs() / f"{int(self.criado_em)}-{self.id}.log"
        self.proc: Optional[subprocess.Popen] = None

    def como_dict(self) -> dict:
        return {"id": self.id, "tipo": self.tipo, "alvo": self.alvo, "status": self.status,
                "codigo": self.codigo, "criado_em": self.criado_em, "inicio": self.inicio,
                "fim": self.fim, "mensagem": self.mensagem}


class Executor:
    """Um trabalho por vez: a ferramenta do usuário aceita um navegador de cada vez."""

    def __init__(self, estado: Estado):
        self.estado = estado
        self.fila: "queue.Queue[Job]" = queue.Queue()
        self.jobs = []
        self._trava = threading.Lock()
        self.atual: Optional[Job] = None
        threading.Thread(target=self._laco, daemon=True).start()

    def listar(self) -> list:
        with self._trava:
            return [j.como_dict() for j in self.jobs[-30:]]

    def _comando(self, job: Job) -> list:
        conf = pb.carregar()
        conector = pb.caminho_conector(conf)
        if not conector or not conector.is_file():
            raise ValueError("Conector não configurado. Rode /painel-criar no Claude Code.")
        python = os.environ.get("PAINEL_PYTHON") or str(pb.python_do_pacote() or sys.executable)
        if job.tipo == "listar":
            return [python, str(conector), "listar", "--saida", str(pb.arq_fila())]
        if job.tipo == "baixar":
            if not (conf.get("conector") or {}).get("baixar"):
                raise ValueError("Este conector não baixa processos.")
            if not pb.regex_identificador(conf).fullmatch(job.alvo):
                raise ValueError("Identificador fora do padrão configurado.")
            return [python, str(conector), "baixar", job.alvo, "--destino",
                    str(pb.pasta_processos(conf))]
        raise ValueError(f"Tipo de tarefa desconhecido: {job.tipo}")

    def enfileirar(self, tipo: str, alvo: str = "") -> Job:
        with self._trava:
            for j in self.jobs:
                if j.tipo == tipo and j.alvo == alvo and j.status in ("aguardando", "executando"):
                    raise FileExistsError("Já existe uma tarefa igual em andamento.")
            job = Job(tipo, alvo)
            self._comando(job)          # valida antes de aceitar
            self.jobs.append(job)
        self.fila.put(job)
        return job

    def cancelar(self, job_id: str) -> bool:
        with self._trava:
            job = next((j for j in self.jobs if j.id == job_id), None)
        if not job or job.status not in ("aguardando", "executando"):
            return False
        job.status = "cancelado"
        if job.proc:
            matar_arvore(job.proc)
        return True

    def encerrar(self) -> None:
        if self.atual and self.atual.proc:
            matar_arvore(self.atual.proc)

    def _laco(self) -> None:
        while True:
            job = self.fila.get()
            if job.status == "cancelado":
                continue
            self.atual = job
            self._executar(job)
            self.atual = None
            self.estado.invalidar()

    def _executar(self, job: Job) -> None:
        job.status, job.inicio = "executando", time.time()
        limite = TIMEOUT_LISTAR if job.tipo == "listar" else TIMEOUT_BAIXAR
        try:
            cmd = self._comando(job)
            env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
            extras = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if WINDOWS \
                else {"start_new_session": True}
            with open(job.log, "w", encoding="utf-8") as saida:
                job.proc = subprocess.Popen(cmd, stdout=saida, stderr=subprocess.STDOUT,
                                            stdin=subprocess.DEVNULL, env=env, **extras)
                try:
                    job.codigo = job.proc.wait(timeout=limite)
                except subprocess.TimeoutExpired:
                    matar_arvore(job.proc)
                    job.mensagem = f"tempo esgotado ({limite // 60} min)"
                    job.codigo = -1
        except Exception as exc:  # noqa: BLE001
            job.mensagem = str(exc)
            job.codigo = -1
        job.fim = time.time()
        if job.status == "cancelado":
            return
        if job.codigo == 0:
            job.status = "concluido"
        elif job.codigo == 2:
            job.status = "parcial"
            job.mensagem = job.mensagem or "resultado parcial: confira o registro"
        else:
            job.status = "falhou"
            job.mensagem = job.mensagem or "falhou: veja o registro"

    def ler_log(self, job_id: str) -> Optional[str]:
        with self._trava:
            job = next((j for j in self.jobs if j.id == job_id), None)
        if not job or not job.log.is_file():
            return None
        return job.log.read_text(encoding="utf-8", errors="replace")[-60000:]


# ------------------------------------------------------------------------ HTTP

class Handler(BaseHTTPRequestHandler):
    estado: Estado = None            # preenchidos em servir()
    executor: Executor = None
    porta: int = pb.PORTA_PADRAO
    server_version = "PainelJuridico/1"

    def log_message(self, *_):
        pass

    # -- utilidades
    def _origem_ok(self) -> bool:
        """Recusa chamadas vindas de outro site (o painel só atende a própria página)."""
        aceitos = {f"127.0.0.1:{self.porta}", f"localhost:{self.porta}"}
        if (self.headers.get("Host") or "") not in aceitos:
            return False
        origem = self.headers.get("Origin")
        if origem and origem.split("://", 1)[-1] not in aceitos:
            return False
        return True

    def _json(self, codigo: int, dados, extras: Optional[dict] = None) -> None:
        corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extras or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(corpo)

    def _texto(self, codigo: int, texto: str, tipo: str = "text/plain") -> None:
        corpo = texto.encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", f"{tipo}; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("X-Content-Type-Options", "nosniff")
        if tipo == "text/html":
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
                             "img-src data:; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(corpo)

    def _corpo(self) -> dict:
        tam = int(self.headers.get("Content-Length") or 0)
        if tam > LIMITE_CORPO:
            raise ValueError("requisição grande demais")
        if not tam:
            return {}
        dados = json.loads(self.rfile.read(tam).decode("utf-8"))
        if not isinstance(dados, dict):
            raise ValueError("corpo deve ser um objeto JSON")
        return dados

    # -- GET
    def do_GET(self):  # noqa: N802
        if not self._origem_ok():
            return self._json(403, {"erro": "origem recusada"})
        rota = self.path.split("?", 1)[0]
        try:
            if rota in ("/", "/index.html"):
                return self._texto(200, ESTATICO.read_text(encoding="utf-8"), "text/html")
            if rota == "/api/estado":
                est = dict(self.estado.obter(forcar="forcar=1" in self.path))
                est["jobs"] = self.executor.listar()
                bruto = json.dumps({k: v for k, v in est.items() if k != "gerado_em"},
                                   ensure_ascii=False, sort_keys=True)
                etag = '"%s"' % hashlib.sha1(bruto.encode("utf-8")).hexdigest()
                if self.headers.get("If-None-Match") == etag:
                    self.send_response(304)
                    self.send_header("ETag", etag)
                    self.end_headers()
                    return
                return self._json(200, est, {"ETag": etag})
            if rota.startswith("/api/jobs/") and rota.endswith("/log"):
                texto = self.executor.ler_log(rota.split("/")[3])
                return self._texto(200 if texto is not None else 404, texto or "registro não encontrado")
            return self._json(404, {"erro": "rota não encontrada"})
        except Exception as exc:  # noqa: BLE001
            return self._json(500, {"erro": str(exc)})

    # -- POST
    def do_POST(self):  # noqa: N802
        if not self._origem_ok():
            return self._json(403, {"erro": "origem recusada"})
        rota = self.path.split("?", 1)[0]
        try:
            d = self._corpo()
            if rota == "/api/anotar":
                pasta = self.estado.resolver_pasta(d.get("pasta"))
                nucleo.anotar(pasta, pendencia=d.get("pendencia"), conferida=d.get("conferida"),
                              tags=d.get("tags"), observacoes=d.get("observacoes"))
                res = {"ok": True}
            elif rota == "/api/pedido":
                pasta = self.estado.resolver_pasta(d.get("pasta"))
                if d.get("acao") == "cancelar":
                    res = {"ok": True, "pedido": nucleo.mudar_pedido(pasta, str(d.get("id")), "cancelado")}
                else:
                    res = {"ok": True, "pedido": nucleo.novo_pedido(pasta, str(d.get("peca")),
                                                                    str(d.get("orientacao") or ""))}
            elif rota == "/api/abrir":
                abrir_pasta(self.estado.resolver_pasta(d.get("pasta")))
                res = {"ok": True}
            elif rota == "/api/lixeira":
                para_lixeira(self.estado.resolver_pasta(d.get("pasta")))
                res = {"ok": True}
            elif rota == "/api/criar_pasta":
                conf = pb.carregar()
                ident = str(d.get("identificador") or "").strip()
                if not pb.regex_identificador(conf).fullmatch(ident):
                    raise ValueError("Identificador fora do padrão configurado.")
                raiz = pb.pasta_processos(conf)
                alvo = raiz / pb.nome_de_pasta(ident)
                (alvo / "minutas").mkdir(parents=True, exist_ok=True)
                res = {"ok": True, "pasta": alvo.name}
            elif rota == "/api/jobs":
                job = self.executor.enfileirar(str(d.get("tipo")), str(d.get("alvo") or ""))
                return self._json(201, {"ok": True, "job": job.como_dict()})
            elif rota.startswith("/api/jobs/") and rota.endswith("/cancelar"):
                res = {"ok": self.executor.cancelar(rota.split("/")[3])}
            elif rota == "/api/processar":
                res = abrir_terminal()
            else:
                return self._json(404, {"erro": "rota não encontrada"})
            self.estado.invalidar()
            return self._json(200, res)
        except FileExistsError as exc:
            return self._json(409, {"erro": str(exc)})
        except PermissionError as exc:
            return self._json(403, {"erro": str(exc)})
        except (ValueError, FileNotFoundError, json.JSONDecodeError) as exc:
            return self._json(400, {"erro": str(exc)})
        except Exception as exc:  # noqa: BLE001
            return self._json(500, {"erro": str(exc)})


# --------------------------------------------------------------- ciclo de vida

def porta_configurada() -> int:
    try:
        return int(os.environ.get("PAINEL_PORTA") or pb.carregar().get("porta") or pb.PORTA_PADRAO)
    except (TypeError, ValueError):
        return pb.PORTA_PADRAO


def ativo(porta: int) -> bool:
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{porta}/api/estado")
        with urllib.request.urlopen(req, timeout=3) as r:
            return json.loads(r.read().decode("utf-8")).get("app") == "painel-juridico"
    except Exception:  # noqa: BLE001
        return False


def servir(porta: int) -> int:
    if ativo(porta):
        print(f"O painel já está rodando em http://127.0.0.1:{porta}")
        return 0
    estado = Estado()
    Handler.estado, Handler.executor, Handler.porta = estado, Executor(estado), porta
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", porta), Handler)
    except OSError as exc:
        print(f"ERRO: a porta {porta} está ocupada por outro programa ({exc}). "
              "Troque com: python painel_base.py definir porta=8771")
        return 1
    arq_pid().write_text(str(os.getpid()), encoding="utf-8")

    def _sair(*_):
        Handler.executor.encerrar()
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    for sinal in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sinal, _sair)
        except (ValueError, OSError):
            pass
    print(f"Painel Jurídico em http://127.0.0.1:{porta} (Ctrl+C para encerrar)", flush=True)
    try:
        httpd.serve_forever()
    finally:
        try:
            arq_pid().unlink()
        except OSError:
            pass
    return 0


def abrir(porta: int, navegador: bool = True) -> int:
    url = f"http://127.0.0.1:{porta}"
    if not ativo(porta):
        log = open(pb.dir_dados() / "servidor.log", "a", encoding="utf-8")
        extras = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000008} if WINDOWS \
            else {"start_new_session": True}
        python = str(pb.python_do_pacote() or sys.executable)   # o ambiente do pacote traz a Lixeira
        subprocess.Popen([python, str(Path(__file__).resolve()), "servir", "--porta", str(porta)],
                         stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, **extras)
        for _ in range(25):
            time.sleep(0.3)
            if ativo(porta):
                break
        else:
            print(f"ERRO: o painel não subiu. Veja {pb.dir_dados() / 'servidor.log'}")
            return 1
    print(f"Painel no ar: {url}")
    if navegador:
        webbrowser.open(url)
    return 0


def parar(porta: int) -> int:
    arq = arq_pid()
    if not arq.is_file():
        print("O painel não está rodando." if not ativo(porta) else
              "O painel está rodando, mas sem registro do processo; feche-o pelo gerenciador de tarefas.")
        return 0
    try:
        pid = int(arq.read_text(encoding="utf-8").strip())
        if WINDOWS:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
        else:
            os.kill(pid, signal.SIGTERM)
    except (ValueError, ProcessLookupError, PermissionError, OSError):
        pass
    for _ in range(20):
        if not ativo(porta):
            break
        time.sleep(0.25)
    try:
        arq.unlink()
    except OSError:
        pass
    print("Painel encerrado.")
    return 0


def main() -> int:
    pb.utf8_no_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", nargs="?", default="abrir", choices=("abrir", "parar", "status", "servir"))
    ap.add_argument("--porta", type=int, default=None)
    ap.add_argument("--sem-navegador", action="store_true")
    ap.add_argument("--sem-terminal", action="store_true")
    args = ap.parse_args()
    porta = args.porta or porta_configurada()
    if args.sem_terminal:
        os.environ["PAINEL_SEM_TERMINAL"] = "1"
    if args.cmd == "servir":
        return servir(porta)
    if args.cmd == "abrir":
        return abrir(porta, navegador=not args.sem_navegador)
    if args.cmd == "parar":
        return parar(porta)
    print(f"Painel {'no ar' if ativo(porta) else 'parado'} — http://127.0.0.1:{porta}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
