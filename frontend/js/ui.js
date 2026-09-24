// Utilitarios de interface compartilhados.

/** Escapa HTML para impedir injecao ao renderizar texto do modelo ou dos documentos. */
export function escapar(texto = "") {
  return String(texto)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

/**
 * Markdown minimo (negrito, italico, codigo, listas, paragrafos) +
 * transformacao de "[Fonte N]" em botao clicavel que realca a fonte.
 */
export function formatarResposta(texto = "") {
  let html = escapar(texto.trim());

  html = html
    .replace(/`([^`\n]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(?<![*\w])\*([^*\n]+)\*(?!\w)/g, "<em>$1</em>")
    .replace(/\[Fontes?\s*([\d,\s e]+)\]/gi, (_, nums) =>
      nums
        .split(/[,\se]+/)
        .filter(Boolean)
        .map((n) => `<button class="msg__citacao" type="button" data-fonte="${n}" `
                  + `aria-label="Ver fonte ${n}">${n}</button>`)
        .join("")
    );

  const linhas = html.split("\n");
  const saida = [];
  let lista = null;

  for (const linha of linhas) {
    const bruta = linha.trim();
    const ordenada = /^\d+[.)]\s+/.test(bruta);
    const marcador = /^[-*•]\s+/.test(bruta);

    if (ordenada || marcador) {
      const tag = ordenada ? "ol" : "ul";
      if (lista !== tag) {
        if (lista) saida.push(`</${lista}>`);
        saida.push(`<${tag}>`);
        lista = tag;
      }
      saida.push(`<li>${bruta.replace(/^(\d+[.)]|[-*•])\s+/, "")}</li>`);
      continue;
    }

    if (lista) { saida.push(`</${lista}>`); lista = null; }
    if (bruta) saida.push(`<p>${bruta}</p>`);
  }
  if (lista) saida.push(`</${lista}>`);

  return saida.join("");
}

export function formatarTamanho(bytes = 0) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
}

export function formatarData(iso) {
  try {
    return new Date(iso).toLocaleDateString("pt-BR", {
      day: "2-digit", month: "short", year: "numeric",
    });
  } catch { return "—"; }
}

export function toast(mensagem, tipo = "info", duracao = 5000) {
  const caixa = document.getElementById("toasts");
  const el = document.createElement("div");
  el.className = `toast toast--${tipo}`;
  el.textContent = mensagem;
  caixa.appendChild(el);
  setTimeout(() => el.remove(), duracao);
}
