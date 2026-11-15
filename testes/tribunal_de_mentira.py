#!/usr/bin/env python3
"""
"Tribunal de mentira": site local e sintético para testar conectores sem tocar em
ferramenta real. Tem login, três pastas de tarefa com contador, lista paginada e um
botão de escrita ("Assinar em lote") que nenhum conector pode acionar.

    python tribunal_de_mentira.py [--porta 8791]

Usuário: teste   Senha: segredo
GET /_escritas devolve quantas ações de escrita o site recebeu (deve ser sempre 0).
"""
import argparse
import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

POR_PAGINA = 5
PASTAS = {"minutar": ("Minutar decisão", 12), "conferir": ("Conferir expediente", 3),
          "urgentes": ("Urgentes", 0)}
CLASSES = ["Procedimento Comum", "Mandado de Segurança", "Execução Fiscal"]
ESCRITAS = {"n": 0}


def processos(pasta: str):
    base = {"minutar": 100, "conferir": 200, "urgentes": 300}[pasta]
    return [{"numero": f"{base + i:07d}-{(i * 7) % 90 + 10:02d}.2099.0.00.{1000 + i:04d}",
             "classe": CLASSES[i % 3], "assunto": f"Assunto fictício {i + 1}",
             "partes": f"Autor Exemplo {i + 1} × Réu Exemplo {i + 1}", "dias": 3 * i + 1}
            for i in range(PASTAS[pasta][1])]


def pagina(titulo: str, corpo: str) -> bytes:
    return (f"<!doctype html><html lang='pt-BR'><meta charset='utf-8'><title>{titulo}</title>"
            f"<body style='font-family:sans-serif'><h1>{titulo}</h1>{corpo}</body></html>").encode("utf-8")


class H(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def _logado(self) -> bool:
        return "sessao=ok" in (self.headers.get("Cookie") or "")

    def _enviar(self, corpo: bytes, codigo=200, extras=None, tipo="text/html; charset=utf-8"):
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        for k, v in (extras or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(corpo)

    def _ir(self, destino: str, extras=None):
        self._enviar(b"", 302, dict({"Location": destino}, **(extras or {})))

    def do_GET(self):  # noqa: N802
        u = urlparse(self.path)
        if u.path == "/_escritas":
            return self._enviar(json.dumps(ESCRITAS).encode(), tipo="application/json")
        if u.path == "/login":
            return self._enviar(pagina("Acesso", "<form method='post' action='/login'>"
                "<input id='usuario' name='usuario' placeholder='Usuário'> "
                "<input id='senha' name='senha' type='password' placeholder='Senha'> "
                "<button id='entrar' type='submit'>Entrar</button></form>"))
        if not self._logado():
            return self._ir("/login")
        if u.path in ("/", "/painel"):
            itens = "".join(f"<li class='tarefa'><a href='/pasta/{pid}'>{html.escape(nome)}</a> "
                            f"<span class='contador'>{n}</span></li>" for pid, (nome, n) in PASTAS.items())
            return self._enviar(pagina("Painel do usuário", f"<nav id='menu-principal'>Painel</nav>"
                                       f"<ul class='tarefas'>{itens}</ul>"))
        if u.path.startswith("/pasta/"):
            pid = u.path.split("/")[2]
            if pid not in PASTAS:
                return self._enviar(pagina("Não encontrada", ""), 404)
            todos = processos(pid)
            p = max(1, int(parse_qs(u.query).get("p", ["1"])[0]))
            fatia = todos[(p - 1) * POR_PAGINA:p * POR_PAGINA]
            linhas = "".join(f"<tr><td class='numero'><a href='#'>{x['numero']}</a></td><td class='classe'>{x['classe']}</td>"
                             f"<td class='assunto'>{x['assunto']}</td><td class='partes'>{x['partes']}</td>"
                             f"<td class='dias'>{x['dias']} dia(s)</td></tr>" for x in fatia)
            tem_prox = p * POR_PAGINA < len(todos)
            prox = (f"<a class='proxima' href='/pasta/{pid}?p={p + 1}'>Próxima</a>" if tem_prox
                    else "<span class='proxima disabled'>Próxima</span>")
            return self._enviar(pagina(PASTAS[pid][0], f"<nav id='menu-principal'><a href='/painel'>Painel</a></nav>"
                f"<p class='total-registros'>Total: {len(todos)} registro(s)</p>"
                f"<form method='post' action='/assinar'><button class='assinar' type='submit'>Assinar em lote</button></form>"
                f"<table class='processos'><thead><tr><th>Número</th><th>Classe</th><th>Assunto</th><th>Partes</th>"
                f"<th>Na tarefa</th></tr></thead><tbody>{linhas}</tbody></table><div class='paginacao'>{prox}</div>"))
        return self._enviar(pagina("Não encontrada", ""), 404)

    def do_POST(self):  # noqa: N802
        tam = int(self.headers.get("Content-Length") or 0)
        dados = parse_qs(self.rfile.read(tam).decode("utf-8"))
        if self.path == "/login":
            if dados.get("usuario") == ["teste"] and dados.get("senha") == ["segredo"]:
                return self._ir("/painel", {"Set-Cookie": "sessao=ok; Path=/"})
            return self._ir("/login")
        ESCRITAS["n"] += 1
        return self._enviar(pagina("Ação registrada", ""))


def servidor(porta: int) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", porta), H)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--porta", type=int, default=8791)
    porta = ap.parse_args().porta
    print(f"Tribunal de mentira em http://127.0.0.1:{porta} (usuário teste, senha segredo)", flush=True)
    servidor(porta).serve_forever()
