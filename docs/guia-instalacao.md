# Guia de instalação

## 1. Antes de começar

- Tenha o Claude Code funcionando (abra o terminal e digite `claude`).
- Tenha o Python 3.9 ou mais novo. No Windows, instale por https://www.python.org/downloads/
  marcando "Add python.exe to PATH".

## 2. Instalar

Descompacte o ZIP e, dentro da pasta:

- macOS: `sh instalar.sh`
- Windows (PowerShell): `powershell -ExecutionPolicy Bypass -File instalar.ps1`

O instalador copia duas skills (`painel-criar` e `painel-juridico`) e dois comandos para a
pasta do Claude Code, cria um ambiente Python em `~/.projurista/venv` e instala o navegador
Chromium do Playwright. Se já houver versão anterior das skills, ela é guardada em
`~/.claude/backups-projurista/`.

Sem internet na hora, ou com bloqueio de rede: rode `python instalar.py --sem-dependencias`
e, depois, `python instalar.py --dependencias`.

## 3. Construir o seu painel

No Claude Code, digite `/painel-criar`. Tenha à mão:

- o endereço que você abre para entrar na ferramenta;
- a forma de login (senha, código, certificado);
- os nomes das pastas de tarefa que quer acompanhar;
- as peças que você produz e onde guarda modelos e precedentes.

A primeira leitura da fila abre uma janela do navegador: faça o login nela. Nas vezes
seguintes a sessão é reaproveitada até expirar.

## 4. Atualizar e remover

- Atualizar: baixe o novo ZIP e rode o instalador de novo. A sua configuração e o seu
  conector, em `~/.projurista/painel/`, não são tocados.
- Remover: apague `~/.claude/skills/painel-criar`, `~/.claude/skills/painel-juridico`, os dois
  comandos em `~/.claude/commands/` e a pasta `~/.projurista/painel/`. Se guardou a senha,
  remova a entrada `projurista-painel` do cofre de senhas do sistema.
