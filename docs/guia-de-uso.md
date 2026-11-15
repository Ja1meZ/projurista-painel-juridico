# Guia de uso

## O quadro

- **Fila**: processos que estão nas pastas de tarefa escolhidas e ainda não têm pasta no seu
  computador. "Baixar" aparece quando o conector sabe baixar os autos (PJe); "Criar pasta"
  cria a pasta do processo para você guardar os arquivos.
- **Baixado**: há pasta, ainda sem peça.
- **Em elaboração** e **Aguardando conferência**: dependem das peças que existem em
  `minutas/`, conforme você definiu na configuração.
- **Conferido**: você clicou em "Conferido". Só você marca; a IA não.

O painel não move processos por conta própria nem por arrasto: a coluna é consequência do
que existe na pasta. Isso evita cartão dizendo uma coisa e pasta dizendo outra.

## O cartão

- Clique no número para copiar.
- **Anotar**: pendência (deixa o cartão com a borda vermelha), etiquetas e observações. As
  observações entram no contexto dos pedidos de rascunho.
- **Pedir rascunho**: escolha a peça e escreva a orientação (sentido, pontos a enfrentar,
  modelo a seguir). O pedido fica registrado no cartão.
- **Lixeira**: manda a pasta para a Lixeira do sistema (dá para recuperar).

## Pedidos de rascunho

1. Registre os pedidos nos cartões.
2. Clique em "Processar pedidos" (abre o terminal com o Claude Code) ou, numa sessão já
   aberta, digite `/painel-juridico processar`.
3. O Claude lê os autos da pasta, consulta as fontes que você declarou e grava a peça em
   `minutas/`. O cartão muda de coluna sozinho.
4. Confira a peça. Só então marque "Conferido".

O que a IA não faz: citar precedente que não leu nas suas fontes ou nos autos; decidir o
sentido sem avisar; marcar como conferido; mexer na ferramenta do tribunal.

## Onde ficam as coisas

| O quê | Onde |
|---|---|
| Pastas dos processos | a pasta que você escolheu (`/painel-criar`, etapa 6) |
| Peças | `<pasta do processo>/minutas/` |
| Anotações do cartão | `<pasta do processo>/_painel.json` |
| Configuração, sessão, fila | `~/.projurista/painel/` |
