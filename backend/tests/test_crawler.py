import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

import httpx

from app.rag import crawler, loaders
from app.rag.fontes import carregar_manifesto


class CrawlerTest(unittest.TestCase):
    def test_coleta_recoleta_atualiza_e_arquiva(self):
        semente = "https://campus.test/campus"
        pdf_url = "https://campus.test/download/calendario.pdf"
        docx_url = "https://campus.test/campus/edital.docx?download=1"
        pdf = b"%PDF-1.7\nversao 1"
        buffer = io.BytesIO()
        with ZipFile(buffer, "w") as zip_doc:
            zip_doc.writestr("[Content_Types].xml", "<Types/>")
            zip_doc.writestr("word/document.xml", "<document/>")
        docx_status = 200
        requisicoes = []

        def responder(req):
            url = str(req.url)
            requisicoes.append(url)
            if req.url.path == "/robots.txt":
                return httpx.Response(200, text="User-agent: *\nDisallow: /campus/privado.pdf")
            if url == semente:
                return httpx.Response(200, html=f"""<article><h1>Aviso</h1><p>Prazo: 20/12</p>
                  <table><tr><th>Evento</th><th>Data</th></tr><tr><td>Inscrições</td><td>20/12</td></tr></table>
                  <a href="{pdf_url}">Calendário</a><a href="{docx_url}">Edital</a>
                  <a href="https://outro.test/campus/outro.pdf">Externo</a></article>""")
            if url == pdf_url:
                return httpx.Response(200, content=pdf, headers={"content-type": "application/octet-stream"})
            if url == docx_url:
                return httpx.Response(docx_status, content=buffer.getvalue())
            raise AssertionError(url)

        with tempfile.TemporaryDirectory() as d:
            raiz = Path(d)

            def coletar():
                return crawler.coletar(semente, raiz, profundidade=0, max_paginas=1,
                                        intervalo=0, transport=httpx.MockTransport(responder))

            primeira = coletar()
            self.assertEqual(primeira.erros, [])
            self.assertEqual(len(primeira.salvas), 1)
            self.assertEqual(len(primeira.anexos_salvos), 2)
            self.assertIn("| Inscrições | 20/12 |", (raiz / primeira.salvas[0]).read_text())
            fontes = carregar_manifesto(raiz)
            caminhos = {v["tipo"]: raiz / k for k, v in fontes.items()}
            self.assertEqual(caminhos["docx"].read_bytes(), buffer.getvalue())
            self.assertEqual(caminhos["pdf"].read_bytes(), pdf)
            pdf_key = caminhos["pdf"].relative_to(raiz).as_posix()
            self.assertEqual(fontes[pdf_key]["url_origem"], pdf_url)
            self.assertEqual(fontes[pdf_key]["hash_arquivo"], hashlib.sha256(pdf).hexdigest())
            self.assertTrue(all(f["data_coleta"] and f["status"] == "active" for f in fontes.values()))

            mtime = caminhos["pdf"].stat().st_mtime_ns
            segunda = coletar()
            self.assertEqual(len(segunda.inalteradas), 3)
            self.assertEqual(carregar_manifesto(raiz), fontes)
            self.assertEqual(caminhos["pdf"].stat().st_mtime_ns, mtime)

            pdf = b"%PDF-1.7\nversao 2"
            docx_status = 410
            terceira = coletar()
            self.assertEqual(terceira.anexos_salvos, [pdf_key])
            self.assertEqual(caminhos["pdf"].read_bytes(), pdf)
            self.assertEqual(len(terceira.arquivadas), 1)
            self.assertEqual(carregar_manifesto(raiz)[terceira.arquivadas[0]]["status"], "archived")
            self.assertTrue(caminhos["docx"].exists())
            self.assertNotIn(caminhos["docx"], loaders.listar_documentos(raiz))

    def test_robots_redirecionamento_e_limite_de_download(self):
        vistos = []

        def responder(req):
            vistos.append(req.url.path)
            match req.url.path:
                case "/robots.txt":
                    return httpx.Response(200, text="User-agent: *\nDisallow: /campus/privado.pdf")
                case "/campus":
                    return httpx.Response(200, html="""<main>Oi
                      <a href="privado.pdf">a</a><a href="/campus/privado.pdf">b</a>
                      <a href="/campus/grande.pdf">c</a><a href="/campus-vizinho">d</a>
                      <a href="/campus/link.pdf">e</a>
                      <a href="https://campus.test/campus/%2e%2e/fora">f</a></main>""")
                case "/privado.pdf":
                    return httpx.Response(302, headers={"location": "/campus/privado.pdf"})
                case "/campus/grande.pdf":
                    return httpx.Response(200, content=b"%PDF-" + b"a" * 1024)
                case "/campus/link.pdf":
                    return httpx.Response(302, headers={"location": "https://outro.test/fora.pdf"})
                case _:
                    raise AssertionError(req.url)

        with tempfile.TemporaryDirectory() as d:
            r = crawler.coletar("https://campus.test/campus", Path(d), intervalo=0,
                                max_bytes=512, transport=httpx.MockTransport(responder))
            self.assertEqual(r.requisicoes, len(vistos))
            self.assertEqual(r.anexos_salvos, [])
            self.assertEqual(len(r.salvas), 1)
            self.assertTrue(any("robots" in e for e in r.ignoradas))
            self.assertTrue(any("fora do escopo" in e for e in r.erros))
            self.assertTrue(any("limite de bytes" in e for e in r.erros))
            self.assertNotIn("/campus/privado.pdf", vistos)
            self.assertNotIn("/campus-vizinho", vistos)
