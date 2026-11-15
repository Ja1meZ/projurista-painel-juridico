# Solução de problemas

| Sintoma | O que fazer |
|---|---|
| "Faltam dependências" | `python instalar.py --dependencias` na pasta do pacote |
| O navegador fecha ao abrir | tente outro navegador: `painel_base.py definir ferramenta.navegador="chrome"` (ou `msedge`, `firefox`) |
| A ferramenta exige certificado ou extensão | use `chrome` ou `msedge` como navegador e faça o login na janela |
| A janela pede login toda vez | a sessão da ferramenta dura pouco; é esperado. Guardar usuário e senha (`painel_base.py credenciais`) reduz o trabalho quando não há segundo fator |
| Fila vazia ou tarefa "falhou" depois de funcionar | a tela da ferramenta mudou. Veja o "registro" da tarefa no painel e rode `/painel-criar` (manutenção) para retratar a tela de novo |
| "Leitura parcial" | o conector leu menos do que a ferramenta diz ter. Atualize de novo; persistindo, a paginação da receita precisa de ajuste (`/painel-criar`) |
| "Clique recusado" | o conector tentou acionar um botão de escrita e foi barrado. A receita está apontando para o elemento errado: `/painel-criar` |
| Processo não aparece no quadro | a pasta precisa estar diretamente na pasta dos processos e começar pelo número |
| Porta ocupada | `painel_base.py definir porta=8771` |
| "Processar pedidos" não abre o terminal | o painel mostra o comando; abra o terminal e rode-o |
| Lixeira indisponível (Windows) | `python instalar.py --dependencias` (instala o componente da Lixeira) |

Os scripts ficam em `~/.claude/skills/painel-juridico/scripts/`. Registros em
`~/.projurista/painel/dados/` (`servidor.log`, `conector.log`, `jobs/`).

Ao pedir suporte, envie a mensagem de erro e o nome do sistema e do tribunal. Não envie a
fila, retratos de tela nem pastas de processo: contêm dados dos autos.
