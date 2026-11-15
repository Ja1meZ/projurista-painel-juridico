"""
Manifesto de download do PJe.

O manifesto e a unica fonte de verdade sobre completude. Ele e escrito
SEMPRE, inclusive quando o download falha no meio, para que o portao da
skill possa decidir se a pasta esta pronta ou nao.

Regra central:
    completo = convergiu AND falhas == 0 AND baixado == esperado
"""

import json
import os
import tempfile
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Optional


def _sem_acentos(texto: str) -> str:
    decomposto = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in decomposto if not unicodedata.combining(c))

VERSAO_MANIFESTO = 1
NOME_ARQUIVO = "_manifesto_download.json"

# Peca estruturante e a que dá origem ao recurso ou instaura o feito. Serve ao
# aviso de historico truncado (nivel 2 do portao): se NENHUMA delas aparece, a
# timeline provavelmente expoe so a tarefa atual.
#
# A lista precisa cobrir todas as materias. Restringi-la a denuncia e sentenca —
# como na primeira versao — acusava truncamento em todo agravo de instrumento,
# onde nao ha sentenca nos autos do recurso por definicao, e disparava a rota de
# autos completos sem necessidade.
PECAS_ESTRUTURANTES = (
    # criminal
    "denuncia", "denúncia", "queixa", "pronuncia", "pronúncia",
    # decisorias, de qualquer materia. "Despacho" NAO entra: e ato ordinatorio,
    # presente em qualquer expediente corrente, e sua presenca nada diz sobre
    # termos o ato que originou o feito.
    "sentenca", "sentença", "acordao", "acórdão", "decisao", "decisão",
    # instauradoras e recursais
    "peticao inicial", "petição inicial", "inicial",
    "apelacao", "apelação", "agravo", "razoes", "razões", "recurso",
    "embargos", "contrarrazoes", "contrarrazões",
)


class Manifesto:
    """Acumula o estado do download e persiste em disco."""

    def __init__(self, processo: str, rota: str, pasta: Path,
                 id_processo: Optional[str] = None):
        self.processo = processo
        self.rota = rota
        self.pasta = Path(pasta)
        self.id_processo = id_processo
        self.iniciado_em = datetime.now().isoformat(timespec="seconds")

        self.paginacao: dict = {}
        self.metadados: dict = {}
        self.materia: dict = {}
        self.documentos: list = []
        self.duplicatas_descartadas = 0
        self.esperado: Optional[int] = None       # total anunciado pelo PJe, quando conhecido
        self.enumerados = 0                       # quantos a timeline entregou
        self.erro_fatal: Optional[str] = None
        self.avisos: list = []

    # ------------------------------------------------------------------ registro

    def registrar_paginacao(self, dados: dict):
        self.paginacao = dados or {}
        total_pje = self.paginacao.get("contador_total")
        if isinstance(total_pje, int) and total_pje > 0:
            self.esperado = total_pje

    def registrar_materia(self, metadados: dict, deteccao: dict):
        """Classe e assunto da autuacao, mais o perfil de estruturacao inferido."""
        self.metadados = metadados or {}
        self.materia = deteccao or {}

    def registrar_documento(self, doc: dict):
        """doc: id, nome, ordem, ordem_crono, destino, formato, bytes,
        status ('ok'|'falha'), tentativas, erro."""
        self.documentos.append(doc)

    def avisar(self, mensagem: str):
        if mensagem not in self.avisos:
            self.avisos.append(mensagem)

    # ------------------------------------------------------------------ metricas

    @property
    def baixado(self) -> int:
        return sum(1 for d in self.documentos if d.get("status") == "ok")

    @property
    def falhas(self) -> int:
        return sum(1 for d in self.documentos if d.get("status") != "ok")

    @property
    def convergiu(self) -> bool:
        return bool(self.paginacao.get("convergiu"))

    @property
    def completo(self) -> bool:
        """Completo em relacao ao que o PJe anunciou.

        Se o total anunciado nao pode ser lido, exige-se ao menos convergencia
        da paginacao e zero falhas — e o manifesto registra a incerteza.
        """
        if self.erro_fatal:
            return False
        if self.falhas != 0 or not self.convergiu:
            return False
        if self.esperado is None:
            return self.enumerados > 0
        return self.baixado >= self.esperado

    @property
    def indicio_historico_truncado(self) -> bool:
        """A timeline mostra so a tarefa/fase atual.

        Sintoma: nenhuma peca estruturante entre os documentos enumerados,
        apesar de o download ter corrido bem — sinal de que o que se ve e
        apenas o expediente corrente, sem o ato que originou o feito.
        """
        if not self.documentos:
            return True
        nomes = " | ".join(
            _sem_acentos((d.get("nome") or "").lower()) for d in self.documentos)
        return not any(_sem_acentos(p) in nomes for p in PECAS_ESTRUTURANTES)

    # ------------------------------------------------------------------ persistencia

    def como_dict(self) -> dict:
        return {
            "versao": VERSAO_MANIFESTO,
            "processo": self.processo,
            "id_processo": self.id_processo,
            "rota": self.rota,
            "iniciado_em": self.iniciado_em,
            "concluido_em": datetime.now().isoformat(timespec="seconds"),
            "pasta": str(self.pasta),
            "classe_judicial": self.materia.get("classe"),
            "assunto": self.materia.get("assunto"),
            "perfil_estruturacao": self.materia.get("perfil"),
            "confianca_perfil": self.materia.get("confianca"),
            "materia": self.materia,
            "metadados_autuacao": self.metadados,
            "paginacao": self.paginacao,
            "esperado": self.esperado,
            "enumerados": self.enumerados,
            "baixado": self.baixado,
            "falhas": self.falhas,
            "duplicatas_descartadas": self.duplicatas_descartadas,
            "completo": self.completo,
            "indicio_historico_truncado": self.indicio_historico_truncado,
            "erro_fatal": self.erro_fatal,
            "avisos": self.avisos,
            "falhados": [
                {"id": d.get("id"), "nome": d.get("nome"), "erro": d.get("erro")}
                for d in self.documentos if d.get("status") != "ok"
            ],
            "documentos": self.documentos,
        }

    def salvar(self) -> Path:
        """Escrita atomica: grava em temporario e renomeia."""
        self.pasta.mkdir(parents=True, exist_ok=True)
        destino = self.pasta / NOME_ARQUIVO
        dados = json.dumps(self.como_dict(), ensure_ascii=False, indent=2)
        fd, tmp = tempfile.mkstemp(dir=str(self.pasta), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(dados)
            os.replace(tmp, destino)
        except Exception:
            Path(tmp).unlink(missing_ok=True)
            raise
        return destino

    def resumo(self) -> str:
        esperado = self.esperado if self.esperado is not None else "?"
        estado = "COMPLETO" if self.completo else "INCOMPLETO"
        linha = (f"{estado} | esperado={esperado} enumerados={self.enumerados} "
                 f"baixado={self.baixado} falhas={self.falhas}")
        if self.indicio_historico_truncado:
            linha += " | indício de histórico truncado"
        return linha


def ler(pasta: Path) -> Optional[dict]:
    """Le o manifesto de uma pasta de processo, se existir."""
    caminho = Path(pasta) / NOME_ARQUIVO
    if not caminho.exists():
        return None
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except Exception:
        return None
