import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import settings
from app.rag import embeddings, ingest, pipeline, vectorstore
from app.rag.fontes import salvar_manifesto


class IndexacaoTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        raiz = Path(tmp.name)
        self.documentos = raiz / "documentos"
        self.caminho = self.documentos / "portal" / "aviso.md"
        self.caminho.parent.mkdir(parents=True)
        self.nome = "portal/aviso.md"
        pasta = patch.object(settings, "documents_dir", str(self.documentos))
        chroma = patch.object(settings, "chroma_dir", str(raiz / "chroma"))
        cliente = patch.object(vectorstore, "_cliente", None)
        config = patch.object(settings, "collection_name", "meta1_teste")
        for p in (pasta, chroma, cliente, config):
            p.start()
            self.addCleanup(p.stop)

    def escrever(self, texto, status="active"):
        self.caminho.write_text(texto, encoding="utf-8")
        hash_atual = hashlib.sha256(texto.encode()).hexdigest()
        salvar_manifesto(self.documentos, {self.nome: {
            "titulo": "Aviso oficial", "url_origem": "https://campus.test/aviso", "status": status,
            "data_coleta": "2026-01-01T00:00:00+00:00", "hash_arquivo": hash_atual,
        }})
        return hash_atual

    def test_metadados_no_chroma_skip_e_arquivo_arquivado(self):
        sha = self.escrever("Matrículas em 20/12")
        with patch.object(embeddings, "embed_passagens", return_value=[[1.0, 0.0]]) as embed:
            self.assertEqual(ingest.indexar_documento(self.caminho), 1)
            self.assertEqual(ingest.indexar_documento(self.caminho), 1)
            embed.assert_called_once_with(["Matrículas em 20/12"])
        item = vectorstore.buscar([1.0, 0.0], top_k=5, categoria="portal")[0]
        self.assertEqual(item["metadata"], {
            "categoria": "portal", "titulo": "Aviso oficial", "url_origem": "https://campus.test/aviso",
            "pagina": -1, "data_coleta": "2026-01-01T00:00:00+00:00", "hash_arquivo": sha,
            "documento": self.nome, "extensao": "md", "indice": 0, "status_indice": "active",
            "assinatura_pipeline": item["metadata"]["assinatura_pipeline"],
        })
        self.assertEqual(pipeline.formatar_fontes([item])[0]["url"], "https://campus.test/aviso")
        self.assertEqual(vectorstore.buscar([1.0, 0.0], top_k=5, categoria="outra"), [])
        self.escrever("Matrículas em 20/12", status="archived")
        self.assertEqual(ingest.indexar_base()["documentos_removidos"], 1)
        self.assertEqual(vectorstore.chunks_do_documento(self.nome), [])

    def test_falhas_preservam_versao_anterior_e_tombstone_nao_aparece(self):
        self.escrever("Prazo anterior")
        with patch.object(embeddings, "embed_passagens", return_value=[[1.0, 0.0]]):
            ingest.indexar_documento(self.caminho)
        self.escrever("Prazo atual")
        with patch.object(embeddings, "embed_passagens", side_effect=RuntimeError("embedding falhou")):
            with self.assertRaisesRegex(RuntimeError, "embedding falhou"):
                ingest.indexar_documento(self.caminho)
        self.assertEqual(vectorstore.chunks_do_documento(self.nome)[0]["texto"], "Prazo anterior")
        # A dimensao invalida provoca uma falha real de upsert, nao simulada.
        with patch.object(embeddings, "embed_passagens", return_value=[[1.0, 0.0, 0.0]]):
            with self.assertRaises(Exception):
                ingest.indexar_documento(self.caminho)
        self.assertEqual(vectorstore.chunks_do_documento(self.nome)[0]["texto"], "Prazo anterior")
        # Falha de limpeza fisica apos a publicacao nao deixa o chunk velho visivel.
        with (patch.object(embeddings, "embed_passagens", return_value=[[0.0, 1.0]]),
              patch.object(type(vectorstore.get_colecao()), "delete", side_effect=RuntimeError("falha")),
              self.assertLogs(vectorstore.logger, "WARNING")):
            ingest.indexar_documento(self.caminho)
        self.assertEqual(vectorstore.get_colecao().count(), 2)
        self.assertEqual([r["texto"] for r in vectorstore.buscar([1.0, 0.0], 5)], ["Prazo atual"])
        self.assertEqual(vectorstore.estatisticas(), {"documentos": 1, "chunks": 1})


class EmbeddingsTest(unittest.TestCase):
    def test_prefixos_e5(self):
        class Vetor:
            def tolist(self):
                return [1.0]

        with (patch.object(settings, "embedding_model", "intfloat/multilingual-e5-small"),
              patch.object(settings, "embedding_query_prefix", "query: "),
              patch.object(settings, "embedding_passage_prefix", "passage:"),
              patch.object(embeddings, "get_modelo") as get_modelo):
            encode = get_modelo.return_value.encode
            encode.return_value = [Vetor()]
            embeddings.embed_pergunta("Qual é o prazo?")
            encode.assert_called_once_with(["query: Qual é o prazo?"], normalize_embeddings=True)
            encode.reset_mock()
            embeddings.embed_passagens(["Prazo em dezembro"])
            encode.assert_called_once_with(["passage: Prazo em dezembro"], normalize_embeddings=True,
                                           batch_size=32, show_progress_bar=False)
            with patch.object(settings, "embedding_query_prefix", ""):
                with self.assertRaisesRegex(RuntimeError, "query:"):
                    embeddings.embed_pergunta("Falha")
