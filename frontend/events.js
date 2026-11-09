// Gerenciador de Eventos (painel do operador). Nada daqui aparece na tela do visitante.
// Todo texto vindo do servidor entra na página por textContent (nunca innerHTML).
const $ = (selector, root = document) => root.querySelector(selector);

const STATUS_CLASS = { confirmed: "ok", pending: "warn", found: "warn", divergent: "bad", stale: "muted", rejected: "muted" };
const SOURCE_TRUST = { official: "Oficial", candidate: "Candidata (confirmar)", third_party: "Terceiros" };
const HISTORY_KINDS = {
  cadastro: "Cadastro", edicao: "Edição", pesquisa: "Pesquisa", atualizacao: "Atualização", validacao: "Validação", ativacao: "Ativação",
  arquivo: "Arquivo", fonte: "Fonte", erro: "Erro", pesquisa_externa: "Pesquisa externa"
};
const FIELDS = ["name", "area", "description", "start_date", "end_date", "organization", "city", "uf", "venue", "website", "program_url", "objective", "audience", "notes", "welcome"];
const LIST_FIELDS = ["social", "keywords", "reference_documents", "suggested_questions"];

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

export async function api(path, options = {}) {
  const response = await fetch(path, {
    method: options.method || "GET",
    headers: { "Content-Type": "application/json" },
    body: options.body === undefined ? undefined : JSON.stringify(options.body)
  });
  let data = {};
  try {
    data = await response.json();
  } catch {
    // sem corpo JSON
  }
  if (!response.ok) {
    const detail = Array.isArray(data.detail) ? "Dados inválidos." : data.detail;
    throw new Error(detail || "Não foi possível concluir a operação.");
  }
  return data;
}

function formatPeriod(event) {
  const fmt = (value) => (value ? value.split("-").reverse().join("/") : "?");
  return event.start_date === event.end_date ? fmt(event.start_date) : `${fmt(event.start_date)} a ${fmt(event.end_date)}`;
}

function formatStamp(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("pt-BR");
}

export function initEvents() {
  const card = $("#events-card");
  if (!card) return { refresh() {} };
  const list = $("#events-list");
  const summary = $("#events-summary");
  const detailBox = $("#event-detail");
  const dialog = $("#event-dialog");
  const form = $("#event-form");
  const formError = $("#event-form-error");
  const state = { events: [], activeId: null, selected: null, detail: null, timer: null, editing: null };

  function renderBanner(active) {
    const banner = $("#events-active-banner");
    if (!banner) return;
    banner.classList.toggle("is-active", Boolean(active));
    banner.querySelector("span").textContent = active
      ? `EVENTO ATIVO: ${active.name} · ${formatPeriod(active)}${active.simulation ? " · SIMULAÇÃO" : ""}`
      : "Nenhum evento ativo: o robô usa só o conhecimento institucional do Senac.";
  }

  function say(message, bad = false) {
    summary.textContent = message;
    summary.classList.toggle("is-error", bad);
  }

  async function run(action, okMessage) {
    try {
      const result = await action();
      if (okMessage) say(okMessage);
      return result;
    } catch (error) {
      say(error.message, true);
      return null;
    } finally {
      await refresh();
    }
  }

  // ------------------------------------------------------------------ lista
  function renderList() {
    list.replaceChildren();
    if (!state.events.length) {
      list.append(el("li", { class: "events-empty", text: "Nenhum evento cadastrado. Use NOVO EVENTO para começar." }));
      return;
    }
    for (const event of state.events) {
      const selected = state.selected === event.id;
      list.append(
        el("li", { class: `event-row${selected ? " selected" : ""}${event.active ? " is-active" : ""}` },
          el("button", { type: "button", class: "event-row-main", "aria-pressed": String(selected), onclick: () => select(event.id) },
            el("strong", { text: event.name }),
            el("span", { class: "event-meta", text: `${event.area} · ${formatPeriod(event)}${event.city ? ` · ${event.venue ? `${event.venue}, ` : ""}${event.city}${event.uf ? `/${event.uf}` : ""}` : ""}` }),
            el("span", { class: "event-counts", text: `${event.confirmed} confirmada(s) · ${event.pending} pendente(s) · ${event.sources_total} fonte(s)` })),
          el("span", { class: "event-badges" },
            event.simulation ? el("span", { class: "badge muted", text: "SIMULAÇÃO" }) : null,
            // "Ativo" (estado) e "EVENTO ATIVO" (destaque) dizem a mesma coisa: um evento só fica no
            // estado "active" quando é o evento ativo. Mostra só o destaque nesse caso, para não repetir.
            event.active
              ? el("span", { class: "badge ok", text: "● EVENTO ATIVO" })
              : el("span", { class: `badge ${event.state === "archived" ? "muted" : "warn"}`, text: event.state_label }))));
    }
  }

  // ------------------------------------------------------------------ detalhe
  function actionButton(label, handler, kind = "secondary", disabled = false) {
    return el("button", { type: "button", class: `button-${kind}`, onclick: handler, disabled }, label);
  }

  function renderDetail() {
    detailBox.replaceChildren();
    const detail = state.detail;
    if (!detail) {
      detailBox.hidden = true;
      return;
    }
    detailBox.hidden = false;
    const event = detail.event;
    const id = event.id;
    const job = detail.job || {};
    const busy = Boolean(job.running);
    detailBox.append(
      el("div", { class: "event-detail-head" },
        el("div", {}, el("h3", { text: event.name }),
          el("p", { class: "event-meta", text: `${event.area} · ${formatPeriod(event)} · ${event.state_label}${event.simulation ? " · SIMULAÇÃO (dados fictícios)" : ""}` })),
        el("div", { class: "control-actions" },
          actionButton("Editar", () => openForm(event), "secondary", event.state === "archived"),
          actionButton("Pesquisar e preparar evento", () => startResearch(id, "prepare"), "primary", busy || event.state === "archived"),
          actionButton("Atualizar base", () => startResearch(id, "update"), "secondary", busy || event.state === "archived"),
          event.active
            ? actionButton("Desativar", () => run(() => api("/api/events/deactivate", { method: "POST" }), "Evento desativado: os dados foram preservados."), "secondary")
            : actionButton("Ativar evento", () => activate(id, event.name), "primary", event.state === "archived" || event.confirmed === 0),
          event.state === "archived"
            ? actionButton("Reativar do arquivo", () => run(() => api(`/api/events/${id}/unarchive`, { method: "POST" }), "Evento reativado."))
            : actionButton("Arquivar", () => archive(id, event.name), "danger"))),
      renderJob(job),
      el("dl", { class: "event-dl" },
        ...[["Organização", event.organization], ["Local", [event.venue, event.city, event.uf].filter(Boolean).join(", ")], ["Site oficial", event.website], ["Programação", event.program_url],
          ["Objetivo", event.objective], ["Público", event.audience], ["Palavras-chave", (event.keywords || []).join(", ")], ["Observações (internas)", event.notes],
          ["Preparado em", formatStamp(event.last_prepared_at)], ["Última atualização", formatStamp(event.last_updated_at)],
          ["Atualização programada", event.update_interval_hours ? `a cada ${event.update_interval_hours} h` : "desligada"]]
          .filter(([, value]) => value && value !== "—")
          .flatMap(([label, value]) => [el("dt", { text: label }), el("dd", { text: value })])),
      renderSources(id, detail.sources),
      renderCategories(id, detail),
      renderAddItem(id),
      renderHistory(detail.history));
  }

  function renderJob(job) {
    if (job.running) {
      return el("p", { class: "event-job running", role: "status", text: `Pesquisando: ${job.step || "iniciando"}${job.total ? ` (${job.done}/${job.total})` : ""}…` });
    }
    if (!job.finished_at) return el("p", { hidden: true });
    const lines = [job.error ? `Falha: ${job.error}` : `Última pesquisa: ${job.summary || "concluída"}`, ...(job.messages || []), ...(job.failed || []).map((f) => `Fonte com falha: ${f}`)];
    return el("div", { class: `event-job${job.error ? " bad" : ""}`, role: "status" }, ...lines.map((line) => el("p", { text: line })));
  }

  function renderSources(id, sources) {
    const box = el("section", { class: "event-section" }, el("h4", { text: `Fontes (${sources.length})` }));
    if (!sources.length) box.append(el("p", { class: "event-meta", text: "Nenhuma fonte. Informe o site oficial no cadastro ou adicione uma fonte pública abaixo." }));
    const ul = el("ul", { class: "event-sources" });
    for (const source of sources) {
      ul.append(el("li", {},
        el("span", { class: `badge ${source.trust === "official" ? "ok" : "warn"}`, text: SOURCE_TRUST[source.trust] || source.trust }),
        el("a", { href: source.url, target: "_blank", rel: "noopener noreferrer", text: source.title || source.url }),
        el("span", { class: "event-meta", text: source.error ? `erro: ${source.error}` : source.last_ok ? `consultada em ${formatStamp(source.last_ok)}` : "ainda não consultada" }),
        source.trust !== "official" ? actionButton("Marcar como oficial", () => run(() => api(`/api/events/${id}/sources/${source.id}`, { method: "PATCH", body: { trust: "official" } }), "Fonte marcada como oficial."), "secondary") : null,
        actionButton("Remover", () => run(() => api(`/api/events/${id}/sources/${source.id}`, { method: "DELETE" }), "Fonte removida."), "secondary")));
    }
    box.append(ul);
    const input = el("input", { type: "url", placeholder: "https://site-do-evento.org/programacao", "aria-label": "Endereço da nova fonte", autocomplete: "off" });
    const trust = el("select", { "aria-label": "Confiança da fonte" }, el("option", { value: "official", text: "Oficial" }), el("option", { value: "third_party", text: "Terceiros" }));
    box.append(el("form", { class: "inline-form", onsubmit: (e) => { e.preventDefault(); run(() => api(`/api/events/${id}/sources`, { method: "POST", body: { url: input.value.trim(), trust: trust.value } }), "Fonte adicionada."); } },
      input, trust, el("button", { type: "submit", class: "button-secondary", text: "Adicionar fonte" })));
    return box;
  }

  function renderCategories(id, detail) {
    const box = el("section", { class: "event-section" }, el("h4", { text: "Conteúdo organizado por categoria" }));
    const pending = detail.event.pending;
    if (pending) {
      box.append(actionButton(`Aprovar todas as pendentes (${detail.event.counts.pending})`, () => {
        if (confirm("Aprovar todas as informações que aguardam validação? Divergentes e encontradas em fontes não oficiais não são incluídas.")) {
          run(() => api(`/api/events/${id}/approve-pending`, { method: "POST" }), "Informações aprovadas.");
        }
      }, "secondary", detail.event.counts.pending === 0));
    }
    if (!detail.categories.length) box.append(el("p", { class: "event-meta", text: "Ainda não há conteúdo. Use PESQUISAR E PREPARAR EVENTO." }));
    for (const category of detail.categories) {
      const open = category.items.some((item) => item.status !== "confirmed");
      box.append(el("details", { class: "event-category", open },
        el("summary", { text: `${category.label} (${category.items.length})` }),
        ...category.items.map((item) => renderItem(id, item, detail.sources))));
    }
    return box;
  }

  function renderItem(id, item, sources) {
    const origin = (item.source_ids || []).map((sid) => sources.find((s) => s.id === sid)).filter(Boolean).map((s) => s.url);
    const view = el("div", { class: "item-view" },
      el("p", { class: "item-content", text: item.content }),
      el("p", { class: "event-meta", text: `${origin.length ? `Fonte: ${origin.join(" · ")}` : "Origem: cadastro/operador"} · encontrada em ${formatStamp(item.found_at)}${item.approved_by ? ` · aprovada por ${item.approved_by === "auto" ? "regra automática" : "operador"}` : ""}${item.note ? ` · ${item.note}` : ""}` }));
    const row = el("article", { class: `event-item ${STATUS_CLASS[item.status] || ""}` },
      el("div", { class: "item-head" }, el("strong", { text: item.title }), el("span", { class: `badge ${STATUS_CLASS[item.status] || "muted"}`, text: item.status_label })),
      view);
    const actions = el("div", { class: "item-actions" });
    if (item.status !== "confirmed") actions.append(actionButton(item.category === "updates" ? "Aprovar e aplicar" : "Aprovar", () => run(() => api(`/api/events/${id}/items/${item.id}/approve`, { method: "POST" }), "Informação aprovada.")));
    actions.append(actionButton("Editar", () => editItem(id, item, row, actions)));
    if (item.status !== "rejected") actions.append(actionButton("Rejeitar", () => run(() => api(`/api/events/${id}/items/${item.id}/reject`, { method: "POST", body: {} }), "Informação rejeitada.")));
    if ((item.history || []).length > 1) {
      actions.append(el("details", { class: "item-history" }, el("summary", { text: `Histórico (${item.history.length})` }),
        ...item.history.slice().reverse().map((h) => el("p", { class: "event-meta", text: `${formatStamp(h.at)} — ${h.change}${h.from ? `: “${h.from.slice(0, 120)}” → ` : ": "}“${(h.to || "").slice(0, 120)}”` }))));
    }
    row.append(actions);
    return row;
  }

  function editItem(id, item, row, actions) {
    const area = el("textarea", { rows: "3", maxlength: "900", "aria-label": "Texto da informação" });
    area.value = item.content;
    const editor = el("form", { class: "item-editor", onsubmit: (e) => {
      e.preventDefault();
      run(() => api(`/api/events/${id}/items/${item.id}`, { method: "PUT", body: { content: area.value } }), "Informação editada e confirmada.");
    } }, area, el("p", { class: "event-meta", text: "Até 90 palavras (será falado em voz alta). Salvar confirma a informação." }),
      el("button", { type: "submit", class: "button-primary", text: "Salvar e confirmar" }),
      el("button", { type: "button", class: "button-secondary", text: "Cancelar", onclick: () => renderDetail() }));
    actions.replaceWith(editor);
    area.focus();
  }

  function renderAddItem(id) {
    const category = el("select", { "aria-label": "Categoria" },
      ...[["schedule", "Programação"], ["activities", "Atividades"], ["speakers", "Palestrantes"], ["visitor_info", "Informações para visitantes"], ["faq", "Pergunta frequente"], ["location", "Localização"], ["dates", "Datas e horários"], ["about", "Sobre o evento"], ["news", "Notícias"]]
        .map(([value, label]) => el("option", { value, text: label })));
    const title = el("input", { placeholder: "Título", maxlength: "120", required: true, "aria-label": "Título" });
    const content = el("textarea", { rows: "2", placeholder: "Informação confirmada por você (até 90 palavras)", required: true, "aria-label": "Conteúdo" });
    return el("details", { class: "event-section" }, el("summary", { text: "Adicionar informação manualmente" }),
      el("form", { class: "inline-form stacked", onsubmit: (e) => {
        e.preventDefault();
        run(() => api(`/api/events/${id}/items`, { method: "POST", body: { category: category.value, title: title.value, content: content.value } }), "Informação adicionada.");
      } }, category, title, content, el("button", { type: "submit", class: "button-secondary", text: "Adicionar e confirmar" })));
  }

  function renderHistory(history) {
    const ol = el("ol", { class: "event-history" });
    for (const entry of history) {
      ol.append(el("li", {}, el("span", { class: "badge muted", text: HISTORY_KINDS[entry.kind] || entry.kind }), el("span", { text: ` ${entry.summary}` }), el("span", { class: "event-meta", text: ` · ${formatStamp(entry.at)}` })));
    }
    return el("details", { class: "event-section" }, el("summary", { text: `Histórico de pesquisas e alterações (${history.length})` }), history.length ? ol : el("p", { class: "event-meta", text: "Sem registros." }));
  }

  // ------------------------------------------------------------------ ações
  async function select(id) {
    state.selected = id;
    renderList();
    await loadDetail();
  }

  async function loadDetail() {
    if (!state.selected) {
      state.detail = null;
      renderDetail();
      return;
    }
    try {
      state.detail = await api(`/api/events/${state.selected}`);
    } catch (error) {
      state.detail = null;
      state.selected = null;
      say(error.message, true);
    }
    renderDetail();
    renderList();
    watchJob();
  }

  function watchJob() {
    clearTimeout(state.timer);
    if (state.detail && state.detail.job && state.detail.job.running) {
      state.timer = setTimeout(() => refresh(), 1500);
    }
  }

  async function startResearch(id, mode) {
    await run(() => api(`/api/events/${id}/research`, { method: "POST", body: { mode } }), mode === "prepare" ? "Pesquisa iniciada." : "Atualização iniciada.");
  }

  async function activate(id, name) {
    if (!confirm(`Ativar "${name}"? A tela do visitante passa a usar o contexto deste evento; só as informações confirmadas serão usadas.`)) return;
    await run(() => api(`/api/events/${id}/activate`, { method: "POST" }), "Evento ativado.");
  }

  async function archive(id, name) {
    if (!confirm(`Arquivar "${name}"? Os dados são preservados e o evento deixa de ser ativo.`)) return;
    await run(() => api(`/api/events/${id}/archive`, { method: "POST" }), "Evento arquivado.");
  }

  async function refresh() {
    try {
      const data = await api("/api/events");
      state.events = data.events;
      state.activeId = data.active_id;
      const active = data.events.find((e) => e.active);
      renderBanner(active);
      if (!summary.classList.contains("is-error") || !summary.textContent) {
        say(`${data.events.length} evento(s) cadastrado(s).`);  // o evento ativo aparece no destaque acima
      }
      renderList();
      if (state.selected) await loadDetail();
    } catch (error) {
      say(error.message || "Não foi possível carregar os eventos.", true);
    }
  }

  // ------------------------------------------------------------------ formulário
  function openForm(event = null) {
    state.editing = event ? event.id : null;
    form.reset();
    formError.textContent = "";
    $("#event-dialog-title").textContent = event ? "Editar evento" : "Novo evento";
    for (const field of FIELDS) {
      if (form.elements[field]) form.elements[field].value = event ? event[field] || "" : "";
    }
    for (const field of LIST_FIELDS) {
      form.elements[field].value = event ? (event[field] || []).join(field === "keywords" ? ", " : "\n") : "";
    }
    form.elements.update_interval_hours.value = event ? event.update_interval_hours || 0 : 0;
    dialog.showModal();
  }

  form.addEventListener("submit", async (submitEvent) => {
    submitEvent.preventDefault();
    const body = {};
    for (const field of FIELDS) body[field] = form.elements[field].value.trim();
    for (const field of LIST_FIELDS) body[field] = form.elements[field].value;
    body.update_interval_hours = Number(form.elements.update_interval_hours.value) || 0;
    try {
      const saved = state.editing
        ? await api(`/api/events/${state.editing}`, { method: "PUT", body })
        : await api("/api/events", { method: "POST", body });
      dialog.close();
      state.selected = saved.id;
      say(state.editing ? "Evento atualizado." : "Evento cadastrado. Use PESQUISAR E PREPARAR EVENTO.");
      await refresh();
    } catch (error) {
      formError.textContent = error.message;
    }
  });
  $("#event-form-cancel").addEventListener("click", () => dialog.close());
  $("#event-new").addEventListener("click", () => openForm(null));
  $("#event-refresh").addEventListener("click", () => refresh());

  return { refresh };
}
