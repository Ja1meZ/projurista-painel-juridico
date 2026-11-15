---
name: painel-criar
description: "Constrói, em conversa, o Painel Jurídico local do usuário: pergunta qual ferramenta processual ele usa (PJe de qualquer tribunal e grau, eproc, e-SAJ, Projudi ou outra), como entra nela, quais pastas de tarefa e informações quer ver, quais conexões (MCP) tem e onde guarda precedentes e modelos; cria o conector que lê a fila da ferramenta, valida que ele só lê e abre o painel. Use quando o usuário disser 'criar meu painel', 'montar o painel', 'configurar o painel', 'conectar o painel ao PJe/eproc/e-SAJ', 'trocar a senha do painel', 'mudei de unidade', 'mudar as pastas do painel', ou quando o painel acusar configuração incompleta ou conector com erro."
---

# Painel Jurídico — construção

Você conduz o usuário, em conversa, até ter um painel local funcionando com a ferramenta
dele. O usuário típico é servidor ou assessor, não técnico: uma pergunta de cada vez,
linguagem simples, e diga o que vai acontecer antes de abrir qualquer janela.

Nos comandos, use `python` no lugar de `python3` no Windows. Atalhos usados abaixo:

    BASE=~/.claude/skills/painel-juridico/scripts
    CRIAR=~/.claude/skills/painel-criar/scripts

## Regras que não se negociam

1. Somente leitura. O painel e o conector nunca assinam, movimentam, enviam, salvam ou
   alteram nada na ferramenta. Se o usuário pedir isso, explique que não faz parte do pacote.
2. A senha nunca passa pela conversa nem por argumento de comando. Ou o usuário a digita no
   terminal (sem eco), ou digita direto na janela do navegador.
3. Segundo fator, certificado digital, token e captcha são sempre do usuário, na janela.
4. Não invente seletores nem dados: o conector é escrito a partir do que foi visto nas telas.
5. Os dados da ferramenta ficam na máquina do usuário (`~/.projurista/painel/`). Não os copie
   para outros lugares nem os cole em serviços externos.
6. Nada é ligado ao painel sem passar por `conector_util.py validar`.
7. Antes de automatizar, pergunte se o órgão do usuário permite acesso automatizado de leitura
   ao sistema. Se ele não souber, recomende consultar a área de TI e siga só com o que ele
   autorizar; registre a resposta nas observações.

## Etapa 0 — Situação atual

```bash
python3 $BASE/painel_base.py mostrar
```

Diga em duas linhas o que já existe e o que falta. Se o usuário só quer refazer uma parte
(senha, pastas, peças, referências), vá direto à etapa correspondente.

## Etapa 1 — Ferramenta e acesso

Pergunte, uma coisa por vez:

- Qual sistema: PJe, eproc, e-SAJ, Projudi, outro (nome).
- Tribunal ou órgão e grau (ex.: "TJ do estado X, 1º grau").
- O endereço exato que ele abre para trabalhar (peça que copie da barra do navegador, já
  na tela inicial depois do login, se possível).
- Como entra: usuário e senha; usuário, senha e código; certificado ou token; outro.
- Navegador: o padrão é o Chromium que acompanha o pacote. Certificado digital ou extensão
  do tribunal pedem o navegador instalado: `chrome` ou `msedge`.

Grave (exemplo):

```bash
python3 $BASE/painel_base.py definir ferramenta.sistema="PJe" ferramenta.tribunal="..." ferramenta.grau="1º grau" ferramenta.url="https://..." ferramenta.login="senha+codigo" ferramenta.navegador="chromium"
```

Se o login for por usuário e senha e ele quiser que o painel preencha sozinho, peça que rode
ele mesmo, digitando na caixa de mensagem (o `!` executa na própria sessão):

```
! python3 ~/.claude/skills/painel-juridico/scripts/painel_base.py credenciais
```

A senha vai para o cofre de senhas do sistema. Se preferir não guardar, tudo funciona com
login manual na janela.

Pergunte também o formato do número do processo. O padrão é o do CNJ
(`0000000-00.0000.0.00.0000`). Se a ferramenta usar outro identificador, grave a expressão
regular em `identificador.regex` e o nome em `identificador.rotulo`.

## Etapa 2 — Conector

### Caminho A — PJe com "Painel do usuário interno"

```bash
python3 $CRIAR/conector_util.py usar pje
python3 ~/.projurista/painel/conector/conector.py sondar        # tempo limite: 600000 ms
```

Avise antes: "Vou abrir o navegador no PJe. Faça o login na janela, se ele pedir."
Leia `~/.projurista/painel/dados/sondagem.json`:

- `perfis`: se houver mais de uma lotação, mostre a lista numerada, pergunte qual é a de
  trabalho, grave `ferramenta.perfil="<texto exato>"` e sonde de novo com `--perfil`.
- `pastas`: siga para a etapa 3.
- `ok: false` com aviso de que o painel não abriu: este PJe tem tela diferente da conhecida
  (o conector foi validado em um tribunal). Não insista: vá para o caminho B.

### Caminho B — qualquer outra ferramenta (guiado)

1. Instale o motor por receita:

   ```bash
   python3 $CRIAR/conector_util.py usar modelo
   ```

2. Reconhecimento. Explique: "Vou abrir a sua ferramenta. Faça o login, vá até a tela onde
   aparecem as suas pastas de tarefa (ou filas, localizadores, caixas) e clique no botão azul
   'Retratar esta tela', no canto inferior direito. Depois abra uma das pastas, espere a lista
   de processos e clique de novo. Se houver mais de uma página, vá à segunda e retrate também.
   No fim, clique em 'Concluir'." Então rode (tempo limite de 600000 ms):

   ```bash
   python3 $CRIAR/reconhecer.py
   ```

   Se o botão não aparecer, repita com `--automatico 8`.

3. Leia os retratos em `~/.projurista/painel/reconhecimento/retrato-NN.json` e escreva
   `~/.projurista/painel/conector/receita.json` seguindo `referencias/receita.md`. Cada
   seletor da receita tem de constar de um retrato. Havendo dúvida entre dois candidatos,
   escolha o mais estável (id e classes descritivas; nunca ids gerados com números longos).

4. Teste e ajuste até fechar:

   ```bash
   python3 ~/.projurista/painel/conector/conector.py sondar
   ```

   Mostre ao usuário as pastas encontradas e as três linhas de amostra e pergunte se conferem
   com o que ele vê na tela. Erro de seletor: corrija a receita e repita. Duas tentativas sem
   avanço na mesma tela: peça novo retrato daquela tela em vez de adivinhar.

5. Se a receita não der conta (lista dentro de componente muito dinâmico, exportação em
   arquivo), edite `conector.py` do usuário, mantendo todo clique em `pb.clicar_leitura` e
   nenhum preenchimento fora do login. O contrato está em `referencias/contrato-conector.md`.

Download de autos: o conector por receita não baixa. O usuário guarda os arquivos na pasta do
processo (o painel cria a pasta pelo botão "Criar pasta"). Só escreva um `baixar` se ele pedir
e depois de retratar a tela dos autos; download é leitura, mas exige a mesma validação.

## Etapa 3 — Pastas de tarefa e informações do cartão

Mostre as pastas da sondagem com as quantidades e pergunte quais ele quer no painel. Grave
os nomes exatamente como vieram:

```bash
python3 $BASE/painel_base.py definir 'pastas_tarefa=["<nome 1>", "<nome 2>"]'
```

Mostre os campos que a ferramenta oferece (`campos` da sondagem) e pergunte quais devem
aparecer no cartão; sugira classe, assunto, partes e dias na tarefa:

```bash
python3 $BASE/painel_base.py definir 'campos_cartao=["classe","assunto","partes","dias_na_tarefa"]'
```

## Etapa 4 — Peças e fases

Pergunte que peças ele produz no dia a dia (ex.: despacho, decisão, sentença; ou relatório,
voto e ementa; ou parecer, manifestação). Para cada uma defina o nome do arquivo e a fase a
que ela leva o processo quando existir:

- `elaboracao` — peça intermediária (ex.: relatório);
- `conferencia` — rascunho pronto para ele conferir (padrão).

```bash
python3 $BASE/painel_base.py definir 'pecas=[{"nome":"Relatório","arquivo":"relatorio.txt","fase":"elaboracao"},{"nome":"Sentença","arquivo":"sentenca.txt"}]'
```

As colunas padrão são Baixado, Em elaboração, Aguardando conferência e Conferido. Só mude
(`fases`) se ele pedir outros nomes; a primeira e a última têm papel fixo (entrada e
conferido pelo usuário).

## Etapa 5 — Conexões e referências

1. Liste para o usuário as conexões (servidores MCP) que você enxerga nesta sessão e
   pergunte quais ele usa no trabalho jurídico. Não presuma: registre só as confirmadas.
2. Pergunte onde ficam os precedentes e a legislação de referência (cofre do Obsidian, Notion,
   Google Drive, pasta do computador, sistema do tribunal, nenhum) e como ele costuma procurar
   (pasta, etiqueta, nome de arquivo).
3. Pergunte onde ficam os modelos de peças e se há preferências de redação.
4. Se existir `~/.projurista/config.json` com um cofre (Cérebro Jurídico do Projurista
   instalado), proponha-o como fonte de precedentes, pela skill `consulta-cofre`.

```bash
python3 $BASE/painel_base.py definir 'referencias={"mcps":["..."],"precedentes":[{"tipo":"...","onde":"...","como":"..."}],"modelos":[{"tipo":"...","onde":"..."}],"observacoes":"..."}'
```

Sem fonte de precedentes, diga com clareza: os rascunhos sairão sem citações de
jurisprudência, porque o pacote não cita de memória.

## Etapa 6 — Pasta dos processos

Pergunte onde guardar as pastas dos processos (uma por processo). Recomende pasta local,
fora de serviços de nuvem pessoais: são autos.

```bash
python3 $BASE/painel_base.py definir pastas.processos="~/Processos"
```

## Etapa 7 — Validação e abertura

```bash
python3 ~/.projurista/painel/conector/conector.py listar        # tempo limite: 1800000 ms
python3 $CRIAR/conector_util.py validar
python3 $CRIAR/reconhecer.py --apagar
python3 $BASE/servidor.py abrir
```

- `validar` reprovado: corrija e repita; não abra o painel com conector reprovado.
- Avisos de contagem (lido menor que o esperado): mostre ao usuário, com os números.
- Com tudo certo, mostre o resumo (`painel_base.py mostrar`), explique os botões do painel em
  três frases e diga como pedir um rascunho: botão "Pedir rascunho" no cartão e, depois,
  "Processar pedidos" (ou `/painel-juridico processar` aqui).

Encerre com o que ficou configurado e o que ficou pendente.

## Manutenção

- Senha trocada: etapa 1 (comando de credenciais). Sessão expirada: basta atualizar a fila e
  fazer o login na janela.
- A ferramenta mudou de tela e a fila veio vazia ou com erro: caminho B a partir do passo 2
  (novo retrato), só para a tela que mudou.
- Mudou de unidade ou de pastas: etapas 2 (sondar) e 3.
- Porta ocupada: `painel_base.py definir porta=8771`.
