---
name: painel-juridico
description: "Painel local (kanban no navegador, só no computador do usuário) que mostra a fila da ferramenta processual dele e em que fase está cada processo — Fila, Baixado, Em elaboração, Aguardando conferência, Conferido —, com anotações, pendências e pedidos de rascunho à IA. Use quando o usuário disser 'abrir o painel', 'painel', 'o que tenho na fila', 'em que fase está', 'atualizar a fila', 'processar os pedidos', 'marcar como conferido', 'registrar pendência', 'parar o painel'. Para criar ou reconfigurar o painel (ferramenta, senha, pastas, peças), use a skill painel-criar."
---

# Painel Jurídico — uso

O painel roda só em `127.0.0.1` e lê duas coisas: a fila da ferramenta do usuário (gravada
pelo conector) e a pasta dos processos. O servidor do painel não envia nada para fora da máquina e nada é alterado na ferramenta.

Nos comandos, use `python` no lugar de `python3` no Windows.

    BASE=~/.claude/skills/painel-juridico/scripts

Se `python3 $BASE/painel_base.py conferir` acusar itens faltando, o painel ainda não foi
construído: use a skill `painel-criar`.

## Comandos

| Pedido | O que fazer |
|---|---|
| abrir | `python3 $BASE/servidor.py abrir` |
| parar | `python3 $BASE/servidor.py parar` |
| status, resumo | `python3 $BASE/nucleo.py resumo` e relate em poucas linhas |
| atualizar a fila | `python3 ~/.projurista/painel/conector/conector.py listar` (tempo limite de 1800000 ms; avise que uma janela vai abrir e pode pedir login). Código 2 = leitura parcial: diga os números. Código 1: relate a mensagem; a fila anterior foi preservada |
| processar | seção "Processar pedidos" |

## Como o painel decide a fase

Pela pasta do processo (`<pasta dos processos>/<número>[ - sufixo]/`):

- sem peça em `minutas/` → primeira coluna (Baixado);
- com peça → a fase que a configuração atribui àquela peça (a mais adiantada vence);
- marcado como conferido pelo usuário → última coluna.

Toda peça é gravada em `minutas/`, com o nome de arquivo definido na configuração
(`painel_base.py mostrar`). Arquivo com outro nome aparece no cartão como fora do padrão e
não muda a fase.

Anotações, pendência, conferência e pedidos ficam em `_painel.json` na pasta do processo.
Nunca edite esse arquivo à mão: use o painel ou a linha de comando abaixo.

## Registrar pelo Claude Code

```bash
python3 $BASE/nucleo.py anotar --pasta "<número ou pasta>" --pendencia "texto"
python3 $BASE/nucleo.py anotar --pasta "<número>" --limpar-pendencia
python3 $BASE/nucleo.py anotar --pasta "<número>" --tag urgente --obs "texto"
python3 $BASE/nucleo.py pedir  --pasta "<número>" --peca <id da peça> --orientacao "texto"
```

`--conferida sim` só a pedido expresso do usuário: conferir é ato dele.

## Processar pedidos

1. Liste os pedidos pendentes:

   ```bash
   python3 $BASE/nucleo.py pedidos --json
   ```

   Lista vazia: diga que não há pedidos e pare.

2. Para cada pedido, na ordem:

   a. Marque em andamento:
      `python3 $BASE/nucleo.py anotar --pasta "<pasta>" --pedido-id <id> --pedido-status em_andamento`

   b. Cumpra o campo `instrucao` do pedido. Ele traz a peça, o arquivo de saída, a orientação
      do usuário, as observações do cartão e as fontes de precedentes e modelos que o usuário
      declarou. Leia os autos na pasta antes de escrever. Se o pedido tiver `alertas` (download
      incompleto, pasta sem arquivos), não redija: registre a pendência e passe ao próximo.

   c. Grave a peça em `<pasta>/minutas/<arquivo>` (texto puro, UTF-8).

   d. Marque concluído (`--pedido-status concluido`). Se não foi possível redigir, volte o
      pedido a `pendente`, registre o motivo com `--pendencia` e siga.

3. Ao final, relate por processo: peça gravada, pontos que você decidiu sozinho e o que
   ficou sem fonte.

Regras de redação, sempre:

- Português do Brasil com acentuação completa. Sem negrito no corpo da peça.
- Não invente fatos: só o que está nos autos da pasta.
- Só cite lei, súmula ou precedente lido nas fontes declaradas pelo usuário, constante dos
  autos ou fornecido por ele. Sem fonte, declare a lacuna; não cite de memória.
- Use apenas as conexões (MCP) que estiverem de fato disponíveis na sessão; se a fonte
  declarada não estiver acessível, avise e prossiga sem as citações que dependeriam dela.
- O sentido da decisão é do usuário. Sem orientação, exponha as alternativas no relato (fora
  da peça) e sinalize o que escolheu.
- Toda peça é rascunho para conferência humana. Não marque como conferido.
- Nunca abra a ferramenta para movimentar, assinar ou juntar a peça: o pacote só lê.

## Problemas comuns

- Painel não abre: `servidor.py status`; veja `~/.projurista/painel/dados/servidor.log`.
- Fila vazia depois de atualizar, ou tarefa que falha: a tela da ferramenta pode ter mudado.
  Abra o registro da tarefa no painel e use a skill `painel-criar` (manutenção).
- Processo não aparece: a pasta precisa estar diretamente dentro da pasta dos processos e
  começar pelo número no formato configurado.
