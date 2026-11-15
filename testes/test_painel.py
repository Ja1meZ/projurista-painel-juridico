#!/usr/bin/env python3
"""Testes do núcleo, da base e do validador. Dados sintéticos; nada fora de pasta temporária.

    python3 -m unittest discover -s testes -v
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
_TMP = tempfile.mkdtemp(prefix="painel-teste-")
os.environ["PROJURISTA_PAINEL_DIR"] = str(Path(_TMP) / "cfg")
os.environ["PROJURISTA_SEM_REEXEC"] = "1"
sys.path.insert(0, str(RAIZ / "skills" / "painel-juridico" / "scripts"))
sys.path.insert(0, str(RAIZ / "skills" / "painel-criar" / "scripts"))

import painel_base as pb  # noqa: E402
import nucleo  # noqa: E402
import conector_util as cu  # noqa: E402

N1, N2, N3 = "0000001-11.2099.0.00.0001", "0000002-22.2099.0.00.0002", "0000003-33.2099.0.00.0003"


def tearDownModule():
    shutil.rmtree(_TMP, ignore_errors=True)


class Base(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(pb.dir_painel(), ignore_errors=True)
        self.raiz = Path(tempfile.mkdtemp(dir=_TMP))
        conf = pb.config_vazia()
        conf["pastas"]["processos"] = str(self.raiz)
        conf["pecas"] = [{"nome": "Relatório", "arquivo": "relatorio.txt", "fase": "elaboracao"},
                         {"nome": "Sentença", "arquivo": "sentenca.txt"}]
        conf["ferramenta"].update(sistema="Teste", url="http://127.0.0.1:1/")
        pb.gravar(conf)

    def pasta(self, nome, minutas=(), autos=1):
        p = self.raiz / nome
        (p / "minutas").mkdir(parents=True)
        for i in range(autos):
            (p / f"doc{i}.pdf").write_text("x")
        for m in minutas:
            (p / "minutas" / m).write_text("x")
        return p

    def fila(self, itens, esperado=None):
        fila = pb.montar_fila([{"id": "a", "nome": "Pasta A", "esperado": esperado}],
                              [{"identificador": i, "pasta_id": "a", "campos": {"classe": "X"}} for i in itens])
        pb.gravar_json_atomico(pb.arq_fila(), fila)
        return fila


class TesteBase(Base):
    def test_permissoes_restritas(self):
        if os.name == "nt":
            self.skipTest("sem permissões POSIX")
        self.assertEqual(pb.arq_config().stat().st_mode & 0o077, 0)
        self.assertEqual(pb.dir_sessao().stat().st_mode & 0o077, 0)

    def test_definir_aninhado_e_json(self):
        pb.definir(["ferramenta.tribunal=TJXX", 'campos_cartao=["classe"]', "porta=8771"])
        conf = pb.carregar()
        self.assertEqual(conf["ferramenta"]["tribunal"], "TJXX")
        self.assertEqual(conf["campos_cartao"], ["classe"])
        self.assertEqual(conf["porta"], 8771)

    def test_definir_recusa_url_e_regex_invalidos(self):
        with self.assertRaises(SystemExit):
            pb.definir(["ferramenta.url=ftp://x"])
        with self.assertRaises(SystemExit):
            pb.definir(["identificador.regex=("])

    def test_pecas_e_fases_padrao(self):
        pecas = pb.pecas()
        self.assertEqual([p["id"] for p in pecas], ["relatorio", "sentenca"])
        self.assertEqual(pecas[1]["fase"], "conferencia")
        self.assertEqual(len(pb.fases()), 4)

    def test_arquivo_de_peca_nao_escapa_de_minutas(self):
        conf = pb.carregar()
        conf["pecas"] = [{"nome": "X", "arquivo": "../../fora.txt"}]
        self.assertEqual(pb.pecas(conf)[0]["arquivo"], "fora.txt")

    def test_texto_proibido(self):
        for t in ("Assinar em lote", "ENVIAR", "Salvar alterações", "Movimentar processo"):
            self.assertTrue(pb.texto_proibido(t), t)
        for t in ("Próxima", "Painel", "Baixar lista de processos", "2"):
            self.assertFalse(pb.texto_proibido(t), t)

    def test_montar_e_validar_fila(self):
        fila = self.fila([N1, N2, N1], esperado=3)
        self.assertEqual(pb.validar_fila(fila), [])
        self.assertEqual(len(fila["itens"]), 2)             # repetido na mesma pasta é descartado
        self.assertFalse(fila["manifesto"]["completo"])     # 2 de 3
        self.assertEqual(pb.codigo_de_saida(fila), 2)
        self.assertTrue(pb.validar_fila({"pastas": [], "itens": [{"pasta_id": "x"}], "manifesto": {}}))


class TesteNucleo(Base):
    def test_fases(self):
        self.pasta(N1)
        self.pasta(N2 + " - Mandado de Segurança", minutas=["relatorio.txt"])
        p3 = self.pasta(N3, minutas=["relatorio.txt", "sentenca.txt", "rascunho.txt"])
        self.pasta("anotacoes-soltas")
        est = nucleo.varrer()
        fases = {p["identificador"]: p["fase"] for p in est["processos"]}
        self.assertEqual(fases, {N1: "baixado", N2: "elaboracao", N3: "conferencia"})
        proc3 = [p for p in est["processos"] if p["identificador"] == N3][0]
        self.assertEqual(proc3["minutas_fora_do_padrao"], ["rascunho.txt"])
        nucleo.anotar(p3, conferida=True)
        self.assertEqual(nucleo.inferir_processo(p3, pb.carregar())["fase"], "conferido")
        nucleo.anotar(p3, conferida=False)
        self.assertEqual(nucleo.inferir_processo(p3, pb.carregar())["fase"], "conferencia")

    def test_pasta_com_prefixo_parecido_nao_entra(self):
        self.pasta(N1 + "9")
        self.assertEqual(nucleo.varrer()["processos"], [])

    def test_anotar_preserva_campos(self):
        p = self.pasta(N1)
        nucleo.anotar(p, pendencia="aguardar", tags=["a", "A", "b"])
        nucleo.anotar(p, observacoes="obs")
        d = nucleo.ler_painel(p)
        self.assertEqual((d["pendencia"], d["tags"], d["observacoes"]), ("aguardar", ["a", "b"], "obs"))
        nucleo.anotar(p, pendencia="")
        self.assertEqual(nucleo.ler_painel(p)["pendencia"], "")

    def test_painel_ilegivel_vira_alerta(self):
        p = self.pasta(N1)
        (p / "_painel.json").write_text("{quebrado")
        self.assertIn("arquivo de anotações ilegível", nucleo.inferir_processo(p, pb.carregar())["alertas"])

    def test_pedidos(self):
        p = self.pasta(N1)
        ped = nucleo.novo_pedido(p, "sentenca", "julgar procedente")
        with self.assertRaises(ValueError):
            nucleo.novo_pedido(p, "sentenca")               # já há pedido aberto
        with self.assertRaises(ValueError):
            nucleo.novo_pedido(p, "inexistente")
        lista = nucleo.listar_pedidos()
        self.assertEqual(len(lista), 1)
        self.assertEqual(lista[0]["saida"], "minutas/sentenca.txt")
        self.assertIn("julgar procedente", lista[0]["instrucao"])
        self.assertIn("não localizou", lista[0]["instrucao"])
        nucleo.mudar_pedido(p, ped["id"], "concluido")
        self.assertEqual(nucleo.listar_pedidos(), [])
        nucleo.novo_pedido(p, "sentenca")                   # concluído libera novo pedido

    def test_instrucao_traz_referencias_do_usuario(self):
        pb.definir(['referencias={"mcps":["Fonte X"],"precedentes":[{"tipo":"Pasta","onde":"~/Prec"}],'
                    '"modelos":["Modelos Y"],"observacoes":"parágrafos curtos"}'])
        p = self.pasta(N1)
        nucleo.novo_pedido(p, "relatorio")
        texto = nucleo.listar_pedidos()[0]["instrucao"]
        for trecho in ("Fonte X", "~/Prec", "Modelos Y", "parágrafos curtos"):
            self.assertIn(trecho, texto)

    def test_fila_cruzada_com_pastas(self):
        self.pasta(N1)
        self.fila([N1, N2], esperado=2)
        est = nucleo.varrer()
        itens = {i["identificador"]: i for i in est["fila"]["itens"]}
        self.assertTrue(itens[N1]["ja_baixado"])
        self.assertFalse(itens[N2]["ja_baixado"])
        self.assertEqual(est["processos"][0]["campos"], {"classe": "X"})
        self.assertEqual(est["processos"][0]["pastas_tarefa"], ["a"])

    def test_fila_invalida_nao_derruba(self):
        pb.arq_fila().write_text("{}")
        est = nucleo.varrer()
        self.assertFalse(est["fila"]["existe"])
        self.assertTrue(est["fila"]["erros"])

    def test_resolver_pasta_recusa_fora_da_raiz(self):
        self.pasta(N1)
        self.assertEqual(nucleo.resolver_pasta(N1).name, N1)
        for ruim in ("..", "../cfg", str(pb.dir_painel()), "/etc"):
            with self.assertRaises(FileNotFoundError):
                nucleo.resolver_pasta(ruim)


class TesteValidador(Base):
    def test_receita_exemplo_aprovada(self):
        erros, _ = cu.checar_receita(RAIZ / "skills/painel-criar/conectores/modelo/receita.exemplo.json")
        self.assertEqual(erros, [])

    def test_receita_com_botao_de_escrita_reprovada(self):
        receita = json.loads((RAIZ / "skills/painel-criar/conectores/modelo/receita.exemplo.json").read_text())
        receita["paginacao"]["proximo"] = "button.assinar"
        arq = Path(_TMP) / "r.json"
        arq.write_text(json.dumps(receita))
        erros, _ = cu.checar_receita(arq)
        self.assertTrue(any("ação de escrita" in e for e in erros))

    def test_codigo_alterado_com_clique_direto_reprovado(self):
        d = Path(tempfile.mkdtemp(dir=_TMP))
        (d / "conector.py").write_text("def listar(p):\n    p.locator('a').click()\n    p.fill('#x', 'y')\n")
        erros, avisos = cu.checar_codigo(d)
        self.assertEqual(len(erros), 2)
        self.assertTrue(avisos)

    def test_codigo_do_pacote_passa(self):
        for tipo in ("pje", "modelo"):
            erros, avisos = cu.checar_codigo(RAIZ / "skills/painel-criar/conectores" / tipo)
            self.assertEqual((erros, avisos), ([], []), tipo)

    def test_fila_fora_do_padrao_reprovada(self):
        self.fila(["ABC-123"])
        erros, _ = cu.checar_fila(pb.arq_fila())
        self.assertTrue(erros)

    def test_usar_modelo_preserva_receita(self):
        self.assertEqual(cu.usar("modelo"), 0)
        receita = pb.dir_conector() / "receita.json"
        receita.write_text('{"minha": 1}')
        cu.usar("modelo")
        self.assertEqual(json.loads(receita.read_text()), {"minha": 1})
        self.assertEqual(pb.carregar()["conector"]["baixar"], False)


if __name__ == "__main__":
    unittest.main()
