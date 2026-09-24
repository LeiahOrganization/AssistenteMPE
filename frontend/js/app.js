// Ponto de entrada: navegacao entre vistas, tema, status do sistema.

import { api } from "./api.js";
import { carregarDocumentos, iniciarDocumentos } from "./documentos.js";
import { definirCategoria, iniciarChat, preencherPergunta } from "./chat.js";
import { escapar } from "./ui.js";

const TITULOS = {
  chat: ["Conversar", "Respostas baseadas nos documentos públicos do campus"],
  documentos: ["Base de Conhecimento", "Documentos que o assistente consulta para responder"],
};

const app = document.getElementById("app");

// ------------------------------------------------------------- navegacao

function mostrarVista(nome, atualizarHash = true) {
  if (!TITULOS[nome]) nome = "chat";
  if (atualizarHash && location.hash.slice(1) !== nome) location.hash = nome;

  document.querySelectorAll(".vista").forEach((v) => {
    v.dataset.ativa = String(v.dataset.vista === nome);
  });
  document.querySelectorAll(".nav__item[data-vista]").forEach((b) => {
    if (b.dataset.vista === nome) b.setAttribute("aria-current", "page");
    else b.removeAttribute("aria-current");
  });

  const [titulo, desc] = TITULOS[nome];
  document.getElementById("topo-titulo").textContent = titulo;
  document.getElementById("topo-desc").textContent = desc;
  app.dataset.menu = "fechado";

  if (nome === "documentos") carregarDocumentos();
  if (nome === "chat") document.getElementById("campo-pergunta").focus();
}

document.querySelectorAll(".nav__item[data-vista]").forEach((botao) => {
  botao.addEventListener("click", () => mostrarVista(botao.dataset.vista));
});

// permite link direto (#documentos) e o botao "voltar" do navegador
window.addEventListener("hashchange", () => mostrarVista(location.hash.slice(1), false));

// ------------------------------------------------------------- menu mobile

const btnMenu = document.getElementById("btn-menu");
btnMenu.addEventListener("click", () => {
  const aberto = app.dataset.menu === "aberto";
  app.dataset.menu = aberto ? "fechado" : "aberto";
  btnMenu.setAttribute("aria-expanded", String(!aberto));
});

// ------------------------------------------------------------- tema

const btnTema = document.getElementById("btn-tema");
const temaSalvo = localStorage.getItem("tema")
  ?? (matchMedia("(prefers-color-scheme: dark)").matches ? "escuro" : "claro");

function aplicarTema(tema) {
  document.documentElement.dataset.tema = tema;
  btnTema.textContent = tema === "escuro" ? "☀️" : "🌙";
  localStorage.setItem("tema", tema);
}
aplicarTema(temaSalvo);

btnTema.addEventListener("click", () => {
  aplicarTema(document.documentElement.dataset.tema === "escuro" ? "claro" : "escuro");
});

// ------------------------------------------------------------- status

async function atualizarStatus() {
  const caixa = document.getElementById("status");
  const texto = document.getElementById("status-texto");
  try {
    const saude = await api.health();
    if (saude.llm_ok) {
      caixa.dataset.estado = "ok";
      texto.innerHTML = `Modelo conectado<br><small>${escapar(saude.llm_model)}</small>`;
    } else {
      caixa.dataset.estado = "erro";
      texto.innerHTML = "Modelo indisponível<br><small>confira o túnel ngrok</small>";
    }
    caixa.title = saude.llm_detalhe;
    if (saude.chunks === 0) mostrarAvisoBaseVazia();
  } catch {
    caixa.dataset.estado = "erro";
    texto.innerHTML = "Servidor fora do ar<br><small>inicie o backend</small>";
  }
}

function mostrarAvisoBaseVazia() {
  if (document.getElementById("aviso-base-vazia")) return;
  const aviso = document.createElement("div");
  aviso.className = "aviso";
  aviso.id = "aviso-base-vazia";
  aviso.innerHTML =
    "<strong>A base de conhecimento está vazia.</strong> Adicione os documentos do campus "
    + "em <code>backend/data/documentos/</code> e rode <code>python -m scripts.ingest</code> "
    + "para que o assistente tenha o que consultar.";
  document.getElementById("mensagens-interno").prepend(aviso);
}

// ------------------------------------------------------------- categorias

async function carregarCategoriasNoFiltro() {
  try {
    const categorias = await api.categorias();
    const select = document.getElementById("filtro-categoria");
    for (const c of categorias) {
      const opcao = document.createElement("option");
      opcao.value = c;
      opcao.textContent = c;
      select.appendChild(opcao);
    }
  } catch { /* base ainda vazia */ }
}

// ------------------------------------------------------------- inicializacao

iniciarChat();
iniciarDocumentos({
  aoPerguntarCategoria(categoria, titulo) {
    mostrarVista("chat");
    definirCategoria(categoria);
    preencherPergunta(`Sobre o documento "${titulo}": `);
  },
});

mostrarVista(location.hash.slice(1) || "chat", false);
atualizarStatus();
carregarCategoriasNoFiltro();
setInterval(atualizarStatus, 60_000);
