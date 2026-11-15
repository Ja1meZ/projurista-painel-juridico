# Contrato do conector

O painel não conhece a ferramenta do usuário. Ele chama um script — o conector — e lê o
arquivo que o conector grava. Qualquer conector que cumpra este contrato funciona.

## Comandos

```
python conector.py sondar [--saida ARQ]
python conector.py listar [--saida ARQ]
python conector.py baixar <identificador> [--destino PASTA]     (opcional)
```

Códigos de saída: `0` completo, `1` erro (o arquivo anterior é preservado), `2` parcial.

- `sondar` grava `~/.projurista/painel/dados/sondagem.json`:
  `{ok, sistema, pastas: [{id, nome, quantidade}], campos: [...], baixar: bool, amostra: [...], avisos: [...]}`.
  O conector de PJe acrescenta `perfis` e `perfil_atual` (lotações do usuário).
- `listar` grava a fila (padrão: `~/.projurista/painel/dados/fila.json`).
- `baixar` grava os arquivos em `<destino>/<identificador>[ - sufixo]/` e, de preferência, um
  `_manifesto_download.json` com `completo`, `esperado` e `baixado`. O painel só oferece o
  botão "Baixar" se `conector.baixar` for verdadeiro na configuração.

## Formato da fila

```json
{
  "versao": 1,
  "gerada_em": "2099-01-01T10:00:00",
  "ferramenta": "nome livre",
  "pastas": [
    {"id": "minutar", "nome": "Minutar decisão", "esperado": 12, "enumerados": 12, "completo": true, "avisos": []}
  ],
  "itens": [
    {"identificador": "0000000-00.0000.0.00.0000", "pasta_id": "minutar",
     "campos": {"classe": "...", "assunto": "...", "partes": "...", "dias_na_tarefa": 3}}
  ],
  "manifesto": {"completo": true, "total_esperado": 12, "total_enumerado": 12, "avisos": []}
}
```

- `esperado` é o que a ferramenta diz ter na pasta (contador). `null` quando ela não informa.
- `completo` da pasta: lido maior ou igual ao esperado. O do manifesto: todas completas.
- Um processo em duas pastas aparece duas vezes em `itens`, uma por pasta.
- `campos` é livre; valores simples (texto, número, sim/não) ou lista de textos.

Use `painel_base.montar_fila(pastas, itens)` para montar e `painel_base.gravar_json_atomico`
para gravar: o formato, as contagens e a permissão do arquivo saem certos.

## Regras

1. Somente leitura: navegar, abrir pasta, paginar, exportar lista, baixar documento. Nada de
   assinar, movimentar, enviar, salvar ou preencher formulário (exceto o de login).
2. Todo clique passa por `painel_base.clicar_leitura(localizador)`; em link de pasta de
   tarefa, `clicar_leitura(localizador, pasta=True)`.
3. Navegador pela classe `painel_base.Navegador`, que guarda a sessão em
   `~/.projurista/painel/sessao/` com permissão restrita e espera o login do usuário.
4. Nunca declarar sucesso sem contagem: se a ferramenta mostra um total, ele entra em
   `esperado`. Falha vira código `1` ou `2` e mensagem clara, não lista vazia silenciosa.
5. Nada de enviar dados a serviços externos, nem de gravar fora de `~/.projurista/painel/` e
   da pasta dos processos.

O validador (`conector_util.py validar`) confere as regras 1, 2 e 4 e o formato.
