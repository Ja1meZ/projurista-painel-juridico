"""
Identificacao da materia do processo e do perfil de estruturacao.

A deteccao NAO se baseia nos nomes das pecas. Foi a primeira ideia, e o acervo
a desmentiu: sobre 68 processos criminais ja estruturados, os nomes mais
frequentes sao "Despacho", "Certidao", "Intimacao", "Sentenca" e "Apelacao" —
identicos aos de um processo civel. "Denuncia" sequer figura entre os mais
comuns, porque a timeline recursal do 2o grau costuma nao trazer a inicial
acusatoria.

A fonte correta e a propria autuacao do PJe, exibida na pagina dos autos:

    <dt>Classe judicial</dt> <dd>RECURSO EM SENTIDO ESTRITO (426)</dd>
    <dt>Assunto</dt>        <dd><li>Prisão em flagrante (7929)</li></dd>

Classe e assunto vem da Tabela Processual Unificada do CNJ, com o codigo entre
parenteses. E dado declarado pelo tribunal, nao inferencia.
"""

import re
import unicodedata

PERFIS = ("criminal", "saude", "pasep", "civel")

# Le o bloco de detalhes da pagina de autos. Estrutura verificada em 01/08/2026.
METADADOS_JS = r"""() => {
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const saida = {};
  for (const dl of document.querySelectorAll('dl.dl-horizontal, #maisDetalhes dl')) {
    const filhos = [...dl.children];
    for (let i = 0; i < filhos.length; i++) {
      if (filhos[i].tagName !== 'DT') continue;
      const chave = norm(filhos[i].textContent).toLowerCase().replace(/:$/, '');
      const dd = filhos[i + 1];
      if (!dd || dd.tagName !== 'DD') continue;
      const itens = [...dd.querySelectorAll('li')].map(li => norm(li.textContent));
      saida[chave] = itens.length ? itens : norm(dd.textContent);
    }
  }
  return saida;
}"""


def _norm(texto) -> str:
    if isinstance(texto, (list, tuple)):
        texto = " | ".join(str(t) for t in texto)
    d = unicodedata.normalize("NFKD", str(texto or ""))
    return "".join(c for c in d if not unicodedata.combining(c)).upper()


# Marcas na CLASSE judicial. A classe e o sinal mais forte: ela declara a
# natureza do feito na autuacao.
CLASSE_CRIMINAL = (
    "CRIMINAL", "PENAL", "HABEAS CORPUS", "RECURSO EM SENTIDO ESTRITO",
    "EXECUCAO PENAL", "AGRAVO EM EXECUCAO", "ACAO PENAL", "QUEIXA",
    "REVISAO CRIMINAL", "CARTA TESTEMUNHAVEL", "CORREICAO PARCIAL",
    "MANDADO DE SEGURANCA CRIMINAL", "EMBARGOS INFRINGENTES E DE NULIDADE",
    "INQUERITO", "PRISAO", "DESAFORAMENTO",
)
CLASSE_CIVEL_EXPLICITA = ("CIVEL", "FAZENDA", "TRIBUTARI", "FISCAL")

# Marcas no ASSUNTO, para os perfis especializados.
ASSUNTO_SAUDE = (
    "SAUDE", "MEDICAMENTO", "TRATAMENTO MEDICO", "FORNECIMENTO DE MEDICAMENTO",
    "INTERNACAO", "UTI", "PLANO DE SAUDE", "PROCEDIMENTO CIRURGICO",
    "TRATAMENTO HOSPITALAR", "HOME CARE", "ERRO MEDICO",
)
ASSUNTO_PASEP = ("PASEP", "PIS/PASEP", "PIS-PASEP", "FUNDO PIS")
# Marcas na COMPETENCIA do orgao, tal como o PJe a declara: "Segundo Grau
# <sede> (Criminal)", "Segundo Grau <sede> (Fazenda)".
COMPETENCIA_CRIMINAL = ("CRIMINAL", "PENAL", "JURI", "EXECUCAO PENAL")
COMPETENCIA_CIVEL = (
    "CIVEL", "FAZENDA", "FAZENDA PUBLICA", "PUBLICA", "EMPRESARIAL",
    "CONSUMIDOR", "FAMILIA", "SUCESSOES", "TRIBUTARI", "PRECATORI",
)

ASSUNTO_CRIMINAL = (
    "CRIME", "TRAFICO", "ROUBO", "FURTO", "HOMICIDIO", "LESAO CORPORAL",
    "ESTELIONATO", "RECEPTACAO", "PRISAO EM FLAGRANTE", "PENA", "EXECUCAO PENAL",
    "PORTE DE ARMA", "ORGANIZACAO CRIMINOSA", "LATROCINIO", "ESTUPRO",
    "VIOLENCIA DOMESTICA", "AMEACA", "PECULATO", "CORRUPCAO",
)


def detectar(metadados: dict, nomes_pecas=None) -> dict:
    """Devolve {perfil, confianca, classe, assunto, sinais, motivo}.

    Confianca:
      alta  — classe judicial declara a natureza, ou assunto especializado
              inequivoco (saude, PASEP)
      media — so o assunto sugere, sem confirmacao da classe
      baixa — nenhum sinal util; a escolha NAO deve ser automatica
    """
    metadados = metadados or {}
    classe_bruta = metadados.get("classe judicial") or metadados.get("classe") or ""
    assunto_bruto = metadados.get("assunto") or ""
    competencia_bruta = metadados.get("competencia") or metadados.get("competência") or ""
    classe = _norm(classe_bruta)
    assunto = _norm(assunto_bruto)
    competencia = _norm(competencia_bruta)
    sinais = []

    # A competencia declarada e o sinal mais direto: o PJe a exibe como
    # "Segundo Grau <sede> (Criminal)" ou "(Fazenda)". Vale mais que classe e
    # assunto, pois nomeia a materia sem intermediacao.
    especializado = any(m in assunto for m in ASSUNTO_PASEP + ASSUNTO_SAUDE)
    if competencia and not especializado:
        if any(m in competencia for m in COMPETENCIA_CRIMINAL):
            sinais.append(f"competência declarada: {competencia_bruta}")
            return _res("criminal", "alta", classe_bruta, assunto_bruto, sinais,
                        "competência do órgão é criminal")
        if any(m in competencia for m in COMPETENCIA_CIVEL):
            sinais.append(f"competência declarada: {competencia_bruta}")
            return _res("civel", "alta", classe_bruta, assunto_bruto, sinais,
                        "competência do órgão é cível")

    if not classe and not assunto:
        # Ultimo recurso: nomes de peca. Sinal fraco por natureza — serve
        # apenas para nao devolver nada quando os metadados faltam.
        nomes = _norm(" | ".join(nomes_pecas or []))
        if "DENUNCIA" in nomes or "INTERROGATORIO" in nomes or "ALEGACOES FINAIS" in nomes:
            return {"perfil": "criminal", "confianca": "baixa",
                    "classe": None, "assunto": None,
                    "sinais": ["peça típica criminal no acervo"],
                    "motivo": "metadados da autuação indisponíveis; inferência fraca"}
        return {"perfil": None, "confianca": "baixa", "classe": None, "assunto": None,
                "sinais": [], "motivo": "classe e assunto não foram lidos na página dos autos"}

    # 1. Especializados: o assunto e decisivo e prevalece sobre a classe, que
    # nesses casos e apenas "APELACAO CIVEL" ou equivalente.
    for marca in ASSUNTO_PASEP:
        if marca in assunto:
            sinais.append(f"assunto contém {marca}")
            return _res("pasep", "alta", classe_bruta, assunto_bruto, sinais,
                        "assunto identifica PASEP")
    for marca in ASSUNTO_SAUDE:
        if marca in assunto:
            sinais.append(f"assunto contém {marca}")
            return _res("saude", "alta", classe_bruta, assunto_bruto, sinais,
                        "assunto identifica judicialização da saúde")

    # 2. Classe judicial declara a natureza criminal.
    for marca in CLASSE_CRIMINAL:
        if marca in classe:
            sinais.append(f"classe contém {marca}")
            return _res("criminal", "alta", classe_bruta, assunto_bruto, sinais,
                        "classe judicial é criminal")

    # 3. Classe explicitamente cível.
    for marca in CLASSE_CIVEL_EXPLICITA:
        if marca in classe:
            sinais.append(f"classe contém {marca}")
            return _res("civel", "alta", classe_bruta, assunto_bruto, sinais,
                        "classe judicial é cível")

    # 4. Classe neutra (ex.: "AGRAVO DE INSTRUMENTO", "APELACAO"): decide o assunto.
    for marca in ASSUNTO_CRIMINAL:
        if marca in assunto:
            sinais.append(f"assunto contém {marca}")
            return _res("criminal", "media", classe_bruta, assunto_bruto, sinais,
                        "classe é neutra, mas o assunto é penal")

    if classe:
        sinais.append(f"classe {classe_bruta!r} sem marca criminal")
        return _res("civel", "media", classe_bruta, assunto_bruto, sinais,
                    "classe não indica matéria criminal nem assunto especializado")

    return _res(None, "baixa", classe_bruta, assunto_bruto, sinais,
                "sinais insuficientes para decidir o perfil")


def _res(perfil, confianca, classe, assunto, sinais, motivo) -> dict:
    return {"perfil": perfil, "confianca": confianca,
            "classe": classe or None, "assunto": assunto or None,
            "sinais": sinais, "motivo": motivo}


# Interface ng2 (Angular) dos autos — verificada em 10/11/2026. Classe, assunto
# e competencia NAO ficam visiveis de inicio: aparecem ao clicar no titulo do
# processo (`p.titulo-topo`, title "Mais detalhes"), dentro de
# `dropdown-detalhes-processo table`, uma linha por campo: rotulo em
# `td[scope=row]` e valor na celula seguinte. O clique so abre um painel.
ABRIR_DETALHES_NG2_JS = r"""() => {
  if (document.querySelector('dropdown-detalhes-processo table tr')) return 'aberto';
  const alvo = document.querySelector('p.titulo-topo');
  if (!alvo) return 'sem-titulo';
  alvo.click();
  return 'clicado';
}"""

METADADOS_NG2_JS = r"""() => {
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const saida = {};
  for (const tr of document.querySelectorAll('dropdown-detalhes-processo table tr')) {
    const tds = tr.querySelectorAll('td');
    if (tds.length < 2) continue;
    const chave = norm(tds[0].textContent).toLowerCase().replace(/:$/, '');
    if (!chave) continue;
    const partes = (tds[1].innerText || tds[1].textContent || '')
      .split('\n').map(norm).filter(Boolean);
    saida[chave] = partes.length > 1 ? partes : (partes[0] || '');
  }
  const topo = document.querySelector('p.titulo-topo');
  if (topo) saida['titulo do processo'] = norm(topo.textContent);
  return saida;
}"""

# Siglas de classe do cabecalho da ng2, usadas so se o painel de detalhes falhar.
SIGLAS_CLASSE = {
    "APCIV": "APELAÇÃO CÍVEL",
    "APCRIM": "APELAÇÃO CRIMINAL",
    "AI": "AGRAVO DE INSTRUMENTO",
    "APELREMNEC": "APELAÇÃO / REMESSA NECESSÁRIA",
    "REMNECCIV": "REMESSA NECESSÁRIA CÍVEL",
    "RSE": "RECURSO EM SENTIDO ESTRITO",
    "AGEXPE": "AGRAVO DE EXECUÇÃO PENAL",
    "HCCRIM": "HABEAS CORPUS CRIMINAL",
    "MSCIV": "MANDADO DE SEGURANÇA CÍVEL",
}


def ler_metadados_ng2(frame, espera: float = 8.0) -> dict:
    """Le classe, assunto e competencia na interface ng2 dos autos."""
    import time
    if frame is None:
        return {}
    try:
        frame.evaluate(ABRIR_DETALHES_NG2_JS)
        dados = {}
        limite = time.time() + espera
        while time.time() < limite:
            dados = frame.evaluate(METADADOS_NG2_JS) or {}
            if dados.get("classe judicial"):
                break
            time.sleep(0.5)
    except Exception:
        return {}

    if not dados.get("classe judicial"):
        sigla = (dados.get("titulo do processo") or "").split(" ")[0]
        por_extenso = SIGLAS_CLASSE.get(_norm(sigla).replace(" ", ""))
        if por_extenso:
            dados["classe judicial"] = por_extenso
        elif sigla and not sigla[:1].isdigit():
            dados["classe judicial"] = sigla
    return dados


def ler_metadados(pagina) -> dict:
    """Le classe, assunto e demais detalhes da pagina de autos aberta."""
    try:
        return pagina.evaluate(METADADOS_JS) or {}
    except Exception:
        return {}
