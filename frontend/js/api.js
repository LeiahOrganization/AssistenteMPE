// Camada de acesso a API do backend.
// Trocar de servidor (ex.: backend tambem exposto por ngrok) e so mudar BASE.

export const BASE = "";

const HEADERS_JSON = {
  "Content-Type": "application/json",
  "ngrok-skip-browser-warning": "true",
};

async function json(rota, opcoes = {}) {
  const resposta = await fetch(`${BASE}${rota}`, {
    headers: { ...HEADERS_JSON, ...(opcoes.headers || {}) },
    ...opcoes,
  });
  if (!resposta.ok) {
    let detalhe = `Erro ${resposta.status}`;
    try {
      const corpo = await resposta.json();
      detalhe = corpo.detail || detalhe;
    } catch { /* resposta sem JSON */ }
    throw new Error(detalhe);
  }
  return resposta.json();
}

export const api = {
  health: () => json("/api/health"),

  estatisticas: () => json("/api/documentos/estatisticas"),

  documentos: () => json("/api/documentos"),

  categorias: () => json("/api/documentos/categorias"),

  chunks: (nome) => json(`/api/documentos/${encodeURI(nome)}/chunks`),

  urlArquivo: (nome) => `${BASE}/api/documentos/${encodeURI(nome)}/arquivo`,

  feedback: (dados) =>
    json("/api/feedback", { method: "POST", body: JSON.stringify(dados) }),

  /**
   * Conversa com streaming (SSE). Chama os callbacks conforme os eventos chegam.
   * @param {object} corpo  { question, history, categoria }
   * @param {object} cb     { onSources, onToken, onDone, onError }
   * @param {AbortSignal} signal
   */
  async chatStream(corpo, cb, signal) {
    const resposta = await fetch(`${BASE}/api/chat/stream`, {
      method: "POST",
      headers: HEADERS_JSON,
      body: JSON.stringify(corpo),
      signal,
    });

    if (!resposta.ok || !resposta.body) {
      throw new Error(`Falha na conexão com o servidor (${resposta.status}).`);
    }

    const leitor = resposta.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await leitor.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const blocos = buffer.split("\n\n");
      buffer = blocos.pop() ?? "";

      for (const bloco of blocos) {
        const linha = bloco.trim();
        if (!linha.startsWith("data:")) continue;
        let evento;
        try {
          evento = JSON.parse(linha.slice(5).trim());
        } catch { continue; }

        if (evento.type === "sources") cb.onSources?.(evento.data);
        else if (evento.type === "token") cb.onToken?.(evento.data);
        else if (evento.type === "done") cb.onDone?.(evento.data);
        else if (evento.type === "error") cb.onError?.(new Error(evento.data));
      }
    }
  },
};
