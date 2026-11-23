import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import settings
from app.rag import pipeline
from scripts import eval_retrieval


def resultado(nome, categoria, score):
    return {"chunk_id": nome, "metadata": {"documento": nome, "categoria": categoria}, "score": score}


class RetrievalTest(unittest.TestCase):
    def test_abstencao_e_limiar_inclusivo(self):
        fraco = resultado("fraco", "faq", 0.49)
        aceito = resultado("aceito", "faq", 0.50)
        with (patch.object(settings, "retrieval_min_score", 0.5),
              patch.object(pipeline.embeddings, "embed_pergunta", return_value=[1.0]),
              patch.object(pipeline.vectorstore, "buscar", return_value=[fraco]) as buscar):
            self.assertEqual(pipeline.recuperar("pergunta", categoria="faq"), [])
            buscar.return_value = [aceito, fraco]
            self.assertEqual(pipeline.recuperar("pergunta", categoria="faq"), [aceito])
            buscar.assert_called_with([1.0], top_k=settings.retrieval_top_k, categoria="faq")

    def test_metricas_e_relatorios_cli(self):
        perguntas = [
            {"pergunta": str(i), "documento_esperado": "faq.md" if i < 3 else None,
             "categoria_esperada": "faq" if i < 3 else None, "tem_resposta": i < 3}
            for i in range(5)
        ]
        certo = resultado("faq.md", "faq", 0.8)
        errado = resultado("faq.md", "outra", 0.9)
        retornos = [[certo], [errado, certo], [errado], [], [errado]]
        with tempfile.TemporaryDirectory() as d:
            origem = Path(d) / "perguntas.json"
            origem.write_text(json.dumps(perguntas), encoding="utf-8")
            for extensao in ("json", "md"):
                saida = Path(d) / f"saida.{extensao}"
                with patch.object(pipeline, "recuperar", side_effect=retornos) as recuperar:
                    self.assertEqual(eval_retrieval.main(["--perguntas", str(origem), "--saida", str(saida)]), 0)
                    self.assertTrue(all(call.kwargs == {"top_k": 5} for call in recuperar.call_args_list))
                texto = saida.read_text(encoding="utf-8")
                if extensao == "json":
                    self.assertEqual(json.loads(texto)["metricas"], {
                        "hit@1": 1 / 3, "hit@5": 2 / 3, "mrr@5": 0.5, "taxa_abstencao_correta": 0.5,
                    })
                else:
                    self.assertIn("Taxa de Abstenção Correta | 50.00%", texto)

    def test_exemplo_e_validacao_de_tipo(self):
        self.assertEqual(len(eval_retrieval.ler_perguntas(eval_retrieval.BASE / "perguntas_teste.json")), 5)
        with tempfile.TemporaryDirectory() as d:
            origem = Path(d) / "perguntas.json"
            origem.write_text(json.dumps([{"pergunta": "x", "tem_resposta": "false"}]))
            with self.assertRaisesRegex(ValueError, "booleano"):
                eval_retrieval.ler_perguntas(origem)
