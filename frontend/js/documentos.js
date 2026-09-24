// Vista "Base de Conhecimento": mostra quais documentos alimentam o RAG,
// quantos chunks cada um gerou e permite inspecionar os trechos indexados.

import { api } from "./api.js";
import { escapar, formatarData, formatarTamanho, toast } from "./ui.js";

let documentos = [];
let categoriaAtiva = "";
let termoBusca = "";
let documentoAberto = null;

const el = {};

export function iniciarDocumentos({ aoPerguntarCategoria }) {
  el.stats = document.getElementById("painel-stats");
  el.grade = document.getElementById("grade-docs");
  el.filtros = document.getElementById("filtros-categoria");
  el.busca = document.getElementById("busca-doc");
  el.gaveta = document.getElementById("gaveta");
  el.gavetaTitulo = document.getElementById("gaveta-titulo");
  el.gavetaSub = document.getElementById("gaveta-sub");
  el.gavetaCorpo = document.getElementById("gaveta-corpo");
  el.linkAbrir = document.getElementById("link-abrir-doc");

  el.busca.addEventListener("input", () => {
    termoBusca = el.busca.value.trim().toLowerCase();
    renderGrade();
  });

  el.filtros.addEventListener("click", (evento) => {
    const botao = evento.target.closest(".filtro");
    if (!botao) return;
    categoriaAtiva = botao.dataset.categoria;
    el.filtros.querySelectorAll(".filtro").forEach((b) =>
      b.setAttribute("aria-pressed", String(b === botao))
    );
    renderGrade();
  });

  el.grade.addEventListener("click", (evento) => {
    const cartao = evento.target.closest(".doc");
    if (cartao) abrirDocumento(cartao.dataset.documento);
  });

  document.getElementById("btn-atualizar-docs").addEventListener("click", () => {
    carregarDocumentos(true);
  });

  document.getElementById("btn-fechar-gaveta").addEventListener("click", fecharGaveta);
  document.getElementById("gaveta-fundo").addEventListener("click", fecharGaveta);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && el.gaveta.dataset.aberta === "true") fecharGaveta();
  });

  document.getElementById("btn-perguntar-doc").addEventListener("click", () => {
    const doc = documentos.find((d) => d.documento === documentoAberto);
    fecharGaveta();
    aoPerguntarCategoria(doc?.categoria ?? "", doc?.titulo ?? "");
  });
}

// ------------------------------------------------------------- carregamento

export async function carregarDocumentos(avisar = false) {
  try {
    const [lista, stats] = await Promise.all([api.documentos(), api.estatisticas()]);
    documentos = lista;
    renderStats(stats);
    renderFiltros();
    renderGrade();
    if (avisar) toast(`${lista.length} documento(s) na base.`);
    return lista;
  } catch (erro) {
    el.grade.innerHTML = `<div class="vazio">
      <span class="vazio__icone" aria-hidden="true">⚠️</span>
      Não foi possível carregar a base: ${escapar(erro.message)}</div>`;
    return [];
  }
}

// ------------------------------------------------------------- renderizacao

function renderStats(stats) {
  const cartoes = [
    ["Arquivos na pasta", stats.arquivos_na_pasta],
    ["Documentos indexados", stats.documentos_indexados],
    ["Trechos (chunks)", stats.chunks],
    ["Trechos por resposta", stats.top_k],
  ];
  el.stats.innerHTML = cartoes.map(([rotulo, valor]) => `
    <div class="stat">
      <div class="stat__valor">${valor}</div>
      <div class="stat__rotulo">${rotulo}</div>
    </div>`).join("") + `
    <div class="stat">
      <div class="stat__valor" style="font-size:.92rem;word-break:break-word">
        ${escapar(stats.modelo_embedding)}</div>
      <div class="stat__rotulo">Modelo de embedding</div>
    </div>`;
}

function renderFiltros() {
  const categorias = [...new Set(documentos.map((d) => d.categoria))].sort();
  el.filtros.innerHTML = [
    `<button class="filtro" type="button" data-categoria=""
             aria-pressed="${categoriaAtiva === "" }">Todas</button>`,
    ...categorias.map((c) => `
      <button class="filtro" type="button" data-categoria="${escapar(c)}"
              aria-pressed="${categoriaAtiva === c}">${escapar(c)}</button>`),
  ].join("");
}

function renderGrade() {
  const visiveis = documentos.filter((d) => {
    const okCategoria = !categoriaAtiva || d.categoria === categoriaAtiva;
    const okBusca = !termoBusca ||
      d.titulo.toLowerCase().includes(termoBusca) ||
      d.documento.toLowerCase().includes(termoBusca);
    return okCategoria && okBusca;
  });

  if (!documentos.length) {
    el.grade.innerHTML = `<div class="vazio">
      <span class="vazio__icone" aria-hidden="true">📂</span>
      <strong>A base de conhecimento ainda está vazia.</strong><br>
      Coloque os documentos do campus em <code>backend/data/documentos/&lt;categoria&gt;/</code>
      e execute <code>python -m scripts.ingest</code>.
    </div>`;
    return;
  }

  if (!visiveis.length) {
    el.grade.innerHTML = `<div class="vazio">
      <span class="vazio__icone" aria-hidden="true">🔍</span>
      Nenhum documento encontrado com esse filtro.</div>`;
    return;
  }

  el.grade.innerHTML = visiveis.map((d) => `
    <button class="doc" type="button" data-documento="${escapar(d.documento)}">
      <div class="doc__topo">
        <span class="doc__icone" aria-hidden="true">${escapar(d.extensao)}</span>
        <span class="doc__titulo">${escapar(d.titulo)}</span>
      </div>
      <div class="doc__meta">
        <span class="etiqueta etiqueta--categoria">${escapar(d.categoria)}</span>
        ${d.url ? '<span class="etiqueta" title="Coletado do portal">🌐 web</span>' : ""}
        <span class="etiqueta ${d.indexado ? "etiqueta--ok" : "etiqueta--off"}">
          ${d.indexado ? `${d.n_chunks} trechos` : "não indexado"}
        </span>
      </div>
      <div class="doc__meta">
        <span>${formatarTamanho(d.tamanho_bytes)}</span>
        <span>·</span>
        <span>${formatarData(d.modificado_em)}</span>
      </div>
    </button>`).join("");
}

// ------------------------------------------------------------- gaveta

async function abrirDocumento(nome) {
  const doc = documentos.find((d) => d.documento === nome);
  if (!doc) return;

  documentoAberto = nome;
  el.gaveta.dataset.aberta = "true";
  el.gavetaTitulo.textContent = doc.titulo;
  el.gavetaSub.textContent =
    `${doc.categoria} · ${doc.documento} · ${formatarTamanho(doc.tamanho_bytes)}`;
  el.linkAbrir.href = doc.url || api.urlArquivo(nome);
  el.linkAbrir.textContent = doc.url ? "🌐 Abrir página no portal" : "📄 Abrir documento original";
  el.gavetaCorpo.innerHTML = `<p class="msg__meta">Carregando trechos indexados…</p>`;
  document.getElementById("btn-fechar-gaveta").focus();

  if (!doc.indexado) {
    el.gavetaCorpo.innerHTML = `<div class="vazio">
      <span class="vazio__icone" aria-hidden="true">⏳</span>
      Este arquivo ainda não foi indexado.<br>
      Rode <code>python -m scripts.ingest</code> no backend para incluí-lo no RAG.
    </div>`;
    return;
  }

  try {
    const chunks = await api.chunks(nome);
    el.gavetaCorpo.innerHTML = `
      <p class="msg__meta" style="margin-top:0">
        ${chunks.length} trecho(s) indexado(s). É este conteúdo que o assistente consulta
        antes de responder.
      </p>
      ${chunks.map((c) => `
        <div class="chunk">
          <div class="chunk__topo">
            <span>trecho ${c.indice + 1}</span>
            ${c.pagina ? `<span>· página ${c.pagina}</span>` : ""}
            <span>· ${c.n_caracteres} caracteres</span>
          </div>
          <p class="chunk__texto">${escapar(c.texto)}</p>
        </div>`).join("")}`;
  } catch (erro) {
    el.gavetaCorpo.innerHTML = `<div class="vazio">
      <span class="vazio__icone" aria-hidden="true">⚠️</span>
      ${escapar(erro.message)}</div>`;
  }
}

function fecharGaveta() {
  el.gaveta.dataset.aberta = "false";
  documentoAberto = null;
}
