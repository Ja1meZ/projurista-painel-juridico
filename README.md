# Painel Jurídico — Projurista

Um painel que roda no seu computador e mostra, numa tela só, a fila da ferramenta processual
que você usa e em que fase está cada processo do seu trabalho. Serve para PJe (qualquer
tribunal e grau), eproc, e-SAJ, Projudi e outros sistemas na web: o painel é montado para
você, em conversa, pelo Claude Code.

O que ele faz:

- lê as pastas de tarefa (ou filas, localizadores, caixas) da sua ferramenta e mostra os
  processos, com os campos que você escolher;
- acompanha cada processo em colunas: Fila, Baixado, Em elaboração, Aguardando conferência,
  Conferido;
- guarda anotações, pendências e etiquetas por processo;
- recebe pedidos de rascunho ("Pedir rascunho") que o Claude Code redige usando os seus
  modelos e as suas fontes de precedentes.

O que ele não faz: não assina, não movimenta, não envia nem altera nada na sua ferramenta.
Só lê. O painel atende apenas em `127.0.0.1`, isto é, só no seu computador.

Projeto independente, mantido pelo Projurista. Não tem vínculo com o CNJ, com tribunais ou
com os fornecedores dos sistemas citados; os nomes PJe, eproc, e-SAJ e Projudi aparecem
apenas para indicar compatibilidade.

## Requisitos

- Claude Code instalado, no terminal ou na aba "Code" do aplicativo de desktop. Não funciona
  no chat comum do Claude (site ou aplicativo), que não tem acesso ao seu computador.
- Python 3.9 ou mais novo.
- macOS ou Windows. Linux deve funcionar, mas não foi testado.

## Instalação

1. Baixe o ZIP da versão mais recente em
   [Releases](https://github.com/Ja1meZ/projurista-painel-juridico/releases) e descompacte.
   Baixe somente deste repositório: cópias de outras origens podem ter sido alteradas.
2. Na pasta descompactada:
   - macOS: `sh instalar.sh`
   - Windows (PowerShell): `powershell -ExecutionPolicy Bypass -File instalar.ps1`
3. Abra o Claude Code e digite `/painel-criar`.

O instalador não pede senha nem dados do seu trabalho. Quem pergunta é a skill, em conversa:
qual ferramenta você usa, o endereço por onde entra, como faz o login, quais pastas de tarefa
e informações quer ver, quais conexões (MCP) você tem e onde guarda precedentes e modelos.

## Uso

| Você diz | Acontece |
|---|---|
| `/painel-juridico` | abre o painel no navegador |
| botão "Atualizar fila" | relê a fila na sua ferramenta (pode pedir login na janela) |
| botão "Pedir rascunho" e depois "Processar pedidos" | o Claude Code redige as peças pedidas |
| `/painel-juridico parar` | encerra o painel |
| `/painel-criar` | refaz qualquer parte da configuração |

Detalhes em `docs/`.

## Avisos importantes — leia antes de usar

- Autos e inteligência artificial. O painel, sozinho, não envia nada para fora do seu
  computador. Mas o Claude Code é um serviço de IA na nuvem: tudo o que ele lê para trabalhar
  é enviado ao serviço da Anthropic, nas condições do seu plano. Isso inclui os autos da
  pasta do processo, quando você pede um rascunho, e os retratos das telas da sua ferramenta,
  durante a configuração guiada. Não use com processos sigilosos, em segredo de justiça ou
  com dados sensíveis sem antes confirmar que as normas do seu órgão e do CNJ sobre uso de
  IA permitem. Na dúvida, não peça rascunho desses processos: o painel funciona sem isso.
- Acesso automatizado. O conector entra na ferramenta com o seu próprio login e apenas lê.
  Ainda assim, verifique se o seu órgão permite acesso automatizado de leitura ao sistema.
- Responsabilidade. O uso é por sua conta e risco. O software é fornecido como está, sem
  garantia de funcionamento, de continuidade ou de suporte (veja `LICENSE`). Você responde
  pelas suas credenciais, pelos dados que acessa e pelo que assina.
- Todo texto produzido é rascunho. A conferência é sempre humana.

## Limites desta versão

- O conector pronto de PJe foi validado em um tribunal. O PJe muda de versão e de tela de
  login de um tribunal para outro; onde o conector pronto não servir, a skill usa o caminho
  guiado (você mostra as telas e ela escreve a leitura sob medida).
- eproc, e-SAJ, Projudi e demais sistemas dependem do caminho guiado, que foi testado apenas
  em um site de demonstração. Espere ajustes na primeira configuração.
- No caminho guiado não há download automático de autos: você guarda os arquivos na pasta
  do processo.
- Windows não foi testado pelo autor.

## Privacidade

Configuração, sessão do navegador e fila ficam em `~/.projurista/painel/`, com acesso
restrito ao seu usuário. A senha, se você optar por guardá-la, vai para o cofre de senhas do
sistema. Os programas do pacote não enviam dados a terceiros; a ressalva é o que o Claude
Code lê durante a conversa, explicada em "Avisos importantes".

## Licença

MIT (arquivo `LICENSE`): uso, cópia e modificação livres, mantido o aviso de autoria, e sem
garantia de qualquer espécie.
