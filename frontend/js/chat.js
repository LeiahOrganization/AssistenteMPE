// Vista de conversa: envio da pergunta, streaming da resposta,
// exibicao das fontes citadas e coleta de feedback.

import { api } from "./api.js";
import { escapar, formatarResposta, toast } from "./ui.js";

const historico = [];      // memoria curta da conversa enviada ao backend
let contador = 0;
let emAndamento = null;    // AbortController da requisicao corrente

const el = {};

export function iniciarChat() {
  el.mensagens = document.getElementById("mensagens");
  el.interno = document.getElementById("mensagens-interno");
  el.boasVindas = document.getElementById("boas-vindas");
  el.form = document.getElementById("form-chat");
  el.campo = document.getElementById("campo-pergunta");
  el.enviar = document.getElementById("btn-enviar");
  el.filtro = document.getElementById("filtro-categoria");

  el.campo.addEventListener("input", () => {
    el.campo.style.height = "auto";
    el.campo.style.height = `${Math.min(el.campo.scrollHeight, 180)}px`;
    el.enviar.disabled = !el.campo.value.trim();
  });

  el.campo.addEventListener("keydown", (evento) => {
    if (evento.key === "Enter" && !evento.shiftKey) {
      evento.preventDefault();
      el.form.requestSubmit();
    }
  });

  el.form.addEventListener("submit", (evento) => {
    evento.preventDefault();
    const pergunta = el.campo.value.trim();
    if (pergunta) enviar(pergunta);
  });

  document.getElementById("sugestoes")?.addEventListener("click", (evento) => {
    const botao = evento.target.closest(".sugestao");
    if (botao) enviar(botao.dataset.pergunta);
  });

  document.getElementById("btn-nova-conversa")?.addEventListener("click", limparConversa);
}

export function preencherPergunta(texto) {
  el.campo.value = texto;
  el.campo.dispatchEvent(new Event("input"));
  el.campo.focus();
}

export function definirCategoria(categoria) {
  if (el.filtro) el.filtro.value = categoria ?? "";
}

export function limparConversa() {
  historico.length = 0;
  el.interno.querySelectorAll(".msg, .aviso").forEach((n) => n.remove());
  el.boasVindas.style.display = "";
  el.campo.focus();
}

// ---------------------------------------------------------------- envio

async function enviar(pergunta) {
  if (emAndamento) emAndamento.abort();
  el.boasVindas.style.display = "none";
  el.campo.value = "";
  el.campo.style.height = "auto";
  el.enviar.disabled = true;

  adicionarMensagemUsuario(pergunta);
  const bot = adicionarMensagemBot();
  historico.push({ role: "user", content: pergunta });

  emAndamento = new AbortController();
  let resposta = "";
  let fontes = [];

  try {
    await api.chatStream(
      {
        question: pergunta,
        history: historico.slice(0, -1).slice(-6),
        categoria: el.filtro?.value || null,
      },
      {
        onSources: (dados) => {
          fontes = dados;
          bot.renderFontes(dados);
        },
        onToken: (pedaco) => {
          resposta += pedaco;
          bot.renderResposta(resposta);
          rolar();
        },
        onDone: (info) => {
          bot.finalizar(pergunta, resposta, fontes, info);
          historico.push({ role: "assistant", content: resposta });
        },
        onError: (erro) => bot.falhar(erro.message),
      },
      emAndamento.signal
    );
  } catch (erro) {
    if (erro.name !== "AbortError") bot.falhar(erro.message);
  } finally {
    emAndamento = null;
    el.campo.focus();
  }
}

function rolar() {
  el.mensagens.scrollTop = el.mensagens.scrollHeight;
}

// ---------------------------------------------------------------- render

function adicionarMensagemUsuario(texto) {
  const no = document.createElement("article");
  no.className = "msg msg--usuario";
  no.innerHTML = `
    <div class="msg__avatar" aria-hidden="true">🙋</div>
    <div class="msg__corpo">
      <div class="msg__bolha"><p>${escapar(texto)}</p></div>
    </div>`;
  el.interno.appendChild(no);
  rolar();
}

function adicionarMensagemBot() {
  const id = `msg-${++contador}`;
  const no = document.createElement("article");
  no.className = "msg msg--bot";
  no.id = id;
  no.innerHTML = `
    <div class="msg__avatar" aria-hidden="true">🎓</div>
    <div class="msg__corpo">
      <div class="msg__bolha">
        <div class="digitando" aria-label="Gerando resposta"><span></span><span></span><span></span></div>
      </div>
      <div class="fontes-container"></div>
      <div class="msg__rodape"></div>
    </div>`;
  el.interno.appendChild(no);
  rolar();

  const bolha = no.querySelector(".msg__bolha");
  const containerFontes = no.querySelector(".fontes-container");
  const rodape = no.querySelector(".msg__rodape");
  let fontesAtuais = [];

  bolha.addEventListener("click", (evento) => {
    const citacao = evento.target.closest(".msg__citacao");
    if (!citacao) return;
    const alvo = no.querySelector(`#${id}-fonte-${citacao.dataset.fonte}`);
    if (!alvo) return;
    no.querySelector("details")?.setAttribute("open", "");
    alvo.dataset.realce = "true";
    alvo.scrollIntoView({ block: "nearest", behavior: "smooth" });
    setTimeout(() => delete alvo.dataset.realce, 2200);
  });

  return {
    renderResposta(texto) {
      bolha.innerHTML = formatarResposta(texto);
    },

    renderFontes(fontes) {
      fontesAtuais = fontes;
      if (!fontes.length) { containerFontes.innerHTML = ""; return; }

      const itens = fontes.map((f, i) => {
        const n = i + 1;
        const pagina = f.pagina ? ` · página ${f.pagina}` : "";
        return `
          <div class="fonte" id="${id}-fonte-${n}">
            <div class="fonte__topo">
              <span class="fonte__numero">${n}</span>
              <span class="fonte__titulo">${escapar(f.titulo || f.documento)}</span>
              <span class="fonte__local">${escapar(f.categoria)}${pagina}</span>
              <span class="fonte__score" title="Similaridade semântica">${(f.score * 100).toFixed(0)}%</span>
            </div>
            <p class="fonte__trecho">${escapar(f.trecho)}</p>
            <div class="fonte__acoes">
              <a class="fonte__link" href="${f.url || api.urlArquivo(f.documento)}"
                 target="_blank" rel="noopener">
                ${f.url ? "Abrir página no portal ↗" : "Abrir documento original ↗"}
              </a>
            </div>
          </div>`;
      }).join("");

      containerFontes.innerHTML = `
        <details class="fontes">
          <summary class="fontes__resumo">
            📎 ${fontes.length} ${fontes.length === 1 ? "fonte consultada" : "fontes consultadas"}
          </summary>
          <div class="fontes__lista">${itens}</div>
        </details>`;
    },

    finalizar(pergunta, resposta, fontes, info = {}) {
      if (!resposta.trim()) {
        bolha.innerHTML = "<p>O modelo não retornou nenhum texto. Tente reformular a pergunta.</p>";
      }
      const semContexto = info.used_context === false;
      rodape.innerHTML = `
        <button class="btn-mini" data-util="1" aria-pressed="false">👍 Útil</button>
        <button class="btn-mini" data-util="0" aria-pressed="false">👎 Não ajudou</button>
        <button class="btn-mini" data-copiar="1">📋 Copiar</button>
        <span class="msg__meta">${semContexto ? "sem trechos na base" : `${fontes.length} fonte(s)`}
          ${info.model ? `· ${escapar(info.model)}` : ""}</span>`;

      rodape.addEventListener("click", async (evento) => {
        const alvo = evento.target.closest("button");
        if (!alvo) return;

        if (alvo.dataset.copiar) {
          await navigator.clipboard.writeText(resposta);
          toast("Resposta copiada.");
          return;
        }

        const util = alvo.dataset.util === "1";
        rodape.querySelectorAll("[data-util]").forEach((b) =>
          b.setAttribute("aria-pressed", String(b === alvo))
        );
        try {
          await api.feedback({
            question: pergunta,
            answer: resposta,
            util,
            sources: fontesAtuais.map((f) => f.documento),
          });
          toast(util ? "Obrigado pelo retorno!" : "Obrigado! Vamos usar isso para melhorar a base.");
        } catch {
          toast("Não foi possível registrar o feedback.", "erro");
        }
      });
      rolar();
    },

    falhar(mensagem) {
      bolha.innerHTML = `<p><strong>Não consegui responder agora.</strong></p><p>${escapar(mensagem)}</p>`;
      rodape.innerHTML = `<span class="msg__meta">Verifique se o túnel do ngrok está ativo.</span>`;
    },
  };
}
