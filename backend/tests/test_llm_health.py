import json
import unittest
from unittest.mock import patch

import httpx
from openai import OpenAI

from app import llm
from app.config import settings
from app.main import health
from app.rag import vectorstore


class GeminiHealthTest(unittest.TestCase):
    def setUp(self):
        for contexto in (
            patch.object(settings, "llm_base_url", "https://generativelanguage.googleapis.com/v1beta/openai/"),
            patch.object(settings, "llm_model", "gemini-2.5-flash"),
            patch.object(vectorstore, "estatisticas", return_value={"documentos": 0, "chunks": 0}),
        ):
            contexto.start()
            self.addCleanup(contexto.stop)
        llm._verificar_gemini.cache_clear()
        self.addCleanup(llm._verificar_gemini.cache_clear)
    def test_placeholder_nao_chama_google(self):
        with (patch.object(settings, "llm_api_key", "COLE_SUA_CHAVE_AQUI"),
              patch.object(llm, "get_client") as get_client):
            resultado = health().model_dump()
            get_client.assert_not_called()
        self.assertFalse(resultado["llm_ok"])
        self.assertIn("LLM_API_KEY", resultado["llm_detalhe"])

    def test_verifica_geracao_e_nao_expoe_erro_remoto(self):
        chave_ficticia = "apenas-uma-chave-ficticia"
        for status in (200, 400, 403, 404, 429):
            with self.subTest(status=status):
                llm._verificar_gemini.cache_clear()
                requests = []

                def responder(req):
                    requests.append(req)
                    self.assertEqual(req.url.path, "/v1beta/openai/chat/completions")
                    self.assertEqual(req.headers["Authorization"], f"Bearer {chave_ficticia}")
                    self.assertEqual(json.loads(req.content)["model"], "gemini-2.5-flash")
                    if status == 200:
                        return httpx.Response(200, json={"choices": [
                            {"index": 0, "message": {"role": "assistant", "content": "OK"}}
                        ]})
                    return httpx.Response(status, json={"error": {"message": chave_ficticia}})

                with (patch.object(settings, "llm_api_key", chave_ficticia),
                      httpx.Client(transport=httpx.MockTransport(responder)) as http_client,
                      OpenAI(base_url=settings.llm_base_url, api_key=chave_ficticia, http_client=http_client) as client,
                      patch.object(llm, "get_client", return_value=client)):
                    resultado = health()
                    self.assertEqual(health(), resultado)
                self.assertEqual(resultado.llm_model, "gemini-2.5-flash")
                self.assertEqual(resultado.llm_ok, status == 200)
                self.assertNotIn(chave_ficticia, resultado.model_dump_json())
                self.assertEqual(len(requests), 1)
