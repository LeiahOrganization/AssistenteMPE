import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz
from docx import Document

from app.rag import chunking, loaders


class LoadersTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.raiz = Path(tmp.name)

    def test_docx_tabela_na_ordem_e_celula_vazia(self):
        caminho = self.raiz / "local.docx"
        doc = Document()
        doc.add_paragraph("Antes")
        tabela = doc.add_table(rows=2, cols=3)
        for i, cabecalho in enumerate(("Evento", "Local", "Data")):
            tabela.cell(0, i).text = cabecalho
        tabela.cell(1, 0).text = "Matrícula"
        tabela.cell(1, 2).text = "20/12"
        doc.add_paragraph("Depois")
        doc.save(caminho)
        self.assertEqual(loaders.carregar_documento(caminho), [(None,
            "Antes\n\n| Evento | Local | Data |\n| --- | --- | --- |\n| Matrícula | | 20/12 |\n\nDepois"
        )])

    def test_html_tabela_com_rowspan(self):
        caminho = self.raiz / "local.html"
        caminho.write_text("""<p>Antes</p><table><tr><th>Curso</th><th>Horário</th></tr>
            <tr><td rowspan="2">Informática</td><td>8h</td></tr><tr><td>13h</td></tr>
            </table><p>Depois</p>""", encoding="utf-8")
        pagina, texto = loaders.carregar_documento(caminho)[0]
        self.assertIsNone(pagina)
        self.assertIn("| Informática | 8h |\n| Informática | 13h |", texto)
        self.assertLess(texto.index("Antes"), texto.index("| Curso"))
        self.assertGreater(texto.index("Depois"), texto.index("| Curso"))

    def test_pdf_tabela_nativa_e_posicao(self):
        caminho = self.raiz / "tabela.pdf"
        with fitz.open() as doc:
            p = doc.new_page()
            p.insert_text((40, 30), "Comunicado com texto suficiente para nao precisar OCR nesta pagina")
            p.insert_text((30, 150), "Texto depois da tabela")
            for x in (30, 130, 230):
                p.draw_line((x, 50), (x, 110))
            for y in (50, 80, 110):
                p.draw_line((30, y), (230, y))
            for x, y, s in [(35, 65, "Evento"), (135, 65, "Data"), (35, 95, "Inscricoes"), (135, 95, "20/12")]:
                p.insert_text((x, y), s)
            doc.save(caminho)
        pagina, texto = loaders.carregar_documento(caminho)[0]
        self.assertEqual(pagina, 1)
        self.assertIn("|Inscricoes|20/12|", texto)
        self.assertEqual(texto.count("Inscricoes"), 1)
        self.assertLess(texto.index("Comunicado"), texto.index("|Evento|"))
        self.assertGreater(texto.index("Texto depois"), texto.index("|Evento|"))

    def test_ocr_automatico_e_pagina_curta_mantida_em_falha(self):
        caminho = self.raiz / "digitalizado.pdf"
        with fitz.open() as doc:
            doc.new_page()
            doc.new_page().insert_text((30, 45), "Aviso curto")
            doc.save(caminho)
        sentinel = object()
        get_text = fitz.Page.get_text

        def texto_com_ocr(pagina, *args, **kwargs):
            if kwargs.get("textpage") is sentinel:
                return "Prazo recuperado pelo OCR: 20/12."
            return get_text(pagina, *args, **kwargs)

        with (patch.object(fitz.Page, "get_textpage_ocr", side_effect=[sentinel, RuntimeError("dados ausentes")]) as ocr,
              patch.object(fitz.Page, "get_text", texto_com_ocr),
              self.assertLogs(loaders.logger, "WARNING") as avisos):
            paginas = loaders.carregar_documento(caminho)
        self.assertEqual(paginas, [(1, "Prazo recuperado pelo OCR: 20/12."), (2, "Aviso curto")])
        self.assertEqual(ocr.call_count, 2)
        self.assertIn("OCR falhou", avisos.output[-1])

    @unittest.skipUnless(
        os.getenv("TESSDATA_PREFIX")
        and (Path(os.environ["TESSDATA_PREFIX"]) / "por.traineddata").is_file(),
        "OCR real requer TESSDATA_PREFIX com por.traineddata",
    )
    def test_ocr_real_em_pdf_rasterizado(self):
        caminho = self.raiz / "raster.pdf"
        with fitz.open() as fonte, fitz.open() as scan:
            pagina = fonte.new_page(width=500, height=200)
            pagina.insert_text((40, 65), "Prazo de inscrição: 20/12.", fontsize=24)
            imagem = pagina.get_pixmap(matrix=fitz.Matrix(3, 3))
            scan.new_page(width=500, height=200).insert_image(pagina.rect, pixmap=imagem)
            scan.save(caminho)
        with patch.dict(os.environ, {"OCR_LANGUAGE": "por"}), self.assertLogs(loaders.logger, "WARNING"):
            self.assertEqual(loaders.carregar_documento(caminho), [(1, "Prazo de inscrição: 20/12.")])


class ChunkingTest(unittest.TestCase):
    def test_paginas_curtas_separadas_sem_perda(self):
        chunks = chunking.segmentar([(1, "Inscrições até 20/12."), (3, "Outra página curta."), (4, "  ")])
        self.assertEqual([(c.pagina, c.texto) for c in chunks], [
            (1, "Inscrições até 20/12."), (3, "Outra página curta.")])

    def test_tabela_longa_repete_cabecalho_sem_quebrar_linhas(self):
        cabecalho = "| Evento | Data |\n| --- | --- |"
        linhas = [f"| Evento {i} | 20/12 |" for i in range(20)]
        chunks = chunking.segmentar([(3, cabecalho + "\n" + "\n".join(linhas))], tamanho=100)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(c.texto.startswith(cabecalho) for c in chunks))
        self.assertEqual([linha for c in chunks for linha in c.texto.splitlines()[2:]], linhas)
