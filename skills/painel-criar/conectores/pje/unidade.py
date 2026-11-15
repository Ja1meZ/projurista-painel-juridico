"""
Ponte entre o núcleo de PJe e a configuração do Painel Jurídico.

O núcleo foi escrito para ler um módulo chamado `unidade`; aqui ele recebe os dados
de ~/.projurista/painel/config.json (bloco `ferramenta`).
"""
from pathlib import Path
from urllib.parse import urlparse

import _inicio  # noqa: F401
import painel_base as pb


def pje() -> dict:
    conf = pb.carregar()
    f = conf.get("ferramenta") or {}
    perfil = f.get("perfil") or ""
    return {"perfil_2g": perfil, "perfil_1g": perfil, "perfil": perfil,
            "navegador": f.get("navegador") or "chromium",
            "pastas_tarefa": conf.get("pastas_tarefa") or [],
            "url": (f.get("url") or "").rstrip("/"),
            "sso": f.get("sso") or "sso.cloud.pje.jus.br",
            "segmento_download": f.get("segmento_download") or ""}


def base() -> str:
    """Endereço da aplicação, sem barra final e sem página (ex.: https://host/pje)."""
    url = pje()["url"]
    if not url:
        raise SystemExit("Endereço do PJe não configurado. Rode /painel-criar.")
    p = urlparse(url)
    caminho = p.path or ""
    # corta em páginas (.seam) e na área nova (/ng2)
    for marca in ("/ng2", "/login", "/Painel", "/Processo"):
        i = caminho.find(marca)
        if i >= 0:
            caminho = caminho[:i]
    if caminho.endswith(".seam"):
        caminho = caminho.rsplit("/", 1)[0]
    return f"{p.scheme}://{p.netloc}{caminho.rstrip('/')}"


def host() -> str:
    p = urlparse(base())
    return f"{p.scheme}://{p.netloc}"


def contexto_web() -> str:
    return urlparse(base()).path.rstrip("/")


credenciais = pb.credenciais
utf8_no_console = pb.utf8_no_console
garantir_ambiente = pb.garantir_ambiente
_restringir = pb.restringir


def sessao_dir(_grau=None) -> Path:
    return pb.dir_sessao()


def pasta_downloads() -> Path:
    return pb.pasta_processos()


def pasta_dados() -> Path:
    return pb.dir_dados()
