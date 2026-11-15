# Como escrever a receita do conector

A receita (`~/.projurista/painel/conector/receita.json`) descreve as telas da ferramenta do
usuário para o motor `conector.py`. É JSON puro. Todo seletor é CSS e deve ter sido visto
num retrato (`reconhecer.py`).

## Do retrato para a receita

| No retrato | Vira na receita |
|---|---|
| `links_com_contador` ou `listas` da tela de pastas: `seletor`, `esqueleto` | `pastas.seletor`, `pastas.nome`, `pastas.quantidade` |
| `tabelas[].seletor_linha` e `classes_das_celulas`, ou `listas[]` com `tem_identificador: true` | `lista.linha`, `lista.identificador`, `lista.campos` |
| `paginacao[]` | `paginacao.proximo` |
| `quadros[]` quando o conteúdo está num quadro interno | `quadro` |
| `formularios[]` da tela de login | `login` (opcional) |
| elemento que só existe depois do login (menu, nome do usuário) | `logado.seletor` |

## Seções

```json
{
  "logado": {"seletor": "#menu", "url_contem": "/painel", "url_nao_contem": "/login"},
  "login": {"usuario": "#usuario", "senha": "#senha", "entrar": "#entrar"},
  "quadro": "iframe#conteudo",
  "passos_iniciais": [{"ir": "/painel"}, {"clicar": "a#tarefas"}, {"esperar": "ul.tarefas li"}, {"pausa": 1}],
  "pastas": {
    "seletor": "ul.tarefas li",
    "nome": {"seletor": "a"},
    "quantidade": {"seletor": ".contador"},
    "clicar_no_link": true,
    "abrir": "clique",
    "voltar": [{"ir": "/painel"}, {"esperar": "ul.tarefas li"}]
  },
  "pastas_fixas": [{"nome": "Conclusos", "url": "/fila?tipo=conclusos"}],
  "lista": {
    "esperar": "table.processos tbody tr",
    "linha": "table.processos tbody tr",
    "identificador": {"seletor": "td:nth-child(1)"},
    "campos": {"classe": {"seletor": "td:nth-child(2)"}, "dias_na_tarefa": {"seletor": "td.dias", "regex": "(\\d+)"}},
    "total": {"seletor": ".total", "regex": "(\\d+)"},
    "pausa": 1
  },
  "paginacao": {"proximo": "a.proxima", "pausa": 1.5}
}
```

- `logado` (obrigatória): como saber que o login terminou. Use um seletor que só exista
  depois do login; `url_contem` e `url_nao_contem` são alternativas ou reforço.
- `login` (opcional): só para usuário e senha simples. Com segundo fator, certificado ou
  captcha, omita: o usuário faz na janela.
- `quadro`: seletor do `iframe` onde está o conteúdo, quando houver.
- `passos_iniciais`: como chegar à tela de pastas depois do login. Cada passo aceita `ir`
  (endereço absoluto ou relativo ao da configuração), `clicar`, `esperar` (com `tempo` em
  segundos) e `pausa`.
- `pastas`: cada elemento casado por `seletor` é uma pasta. `nome` e `quantidade` são
  extratores relativos a ele. Para abrir: clique no elemento (padrão), no link interno
  (`clicar_no_link: true`) ou navegação pelo endereço do link (`"abrir": "href"`). `voltar`
  diz como retornar à tela de pastas (padrão: repetir `passos_iniciais`).
- `pastas_fixas`: alternativa quando as filas são endereços conhecidos, e não uma lista.
- `lista`: `linha` casa cada processo; `identificador` e `campos` são extratores relativos à
  linha; `total` é extrator relativo à página (contador de registros). Sem `total`, o esperado
  é a `quantidade` da pasta.
- `paginacao`: `proximo` é o controle de próxima página; o motor para quando ele some, fica
  desabilitado ou não traz processo novo. Lista de rolagem infinita: `{"rolagem": true}`.

Extrator: `{"seletor": "...", "atributo": "title", "regex": "(\\d+)"}`. Sem `seletor`, usa o
próprio elemento; sem `atributo`, o texto; com `regex`, fica o primeiro grupo.

Nomes de campo recomendados (o painel já tem rótulo para eles): `classe`, `assunto`,
`partes`, `orgao`, `etiquetas`, `prioridade`, `dias_na_tarefa`, `data_chegada`,
`ultima_movimentacao`, `sigilo`. Outros nomes são aceitos e aparecem como foram escritos.

## Cuidados

- Nenhum seletor de `clicar` ou `proximo` pode apontar para botão de ação (assinar, enviar,
  movimentar, salvar...). O motor recusa e o validador reprova. Nome de pasta com verbo
  ("Minutar decisão", "Assinar despacho") é normal: é o nome da tarefa, e o motor só recusa
  o que enviaria um formulário.
- Prefira seletores curtos e estáveis. Evite `nth-child` quando houver classe ou atributo
  descritivo; evite ids com números longos (mudam a cada sessão).
- Sempre que a ferramenta mostrar um total, capture-o: é ele que prova a leitura completa.
- Depois de cada alteração: `conector.py sondar`, conferir a amostra com o usuário, e só
  então `listar` e `conector_util.py validar`.
