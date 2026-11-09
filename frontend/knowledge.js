// Base de Conhecimento (painel do operador): fonte oficial de cursos técnicos, informações extraídas e pendências.
// Só dados reais do servidor; todo texto entra por textContent (nunca innerHTML).
import { api, el } from "/assets/events.js";

const RECORD_STATUS = {
  found: ["Encontrada", "info"], confirmed: ["Confirmada", "ok"], awaiting_validation: ["Aguardando validação", "warn"],
  divergent: ["Divergente", "bad"], stale: ["Desatualizada", "muted"], rejected: ["Rejeitada", "muted"]
};
const RESOLUTION = {
  resolved: ["Resolvida", "ok"], awaiting_validation: ["Informação encontrada, aguardando validação", "warn"], divergent: ["Informação divergente", "bad"],
  unresolved: ["Continua sem solução", "muted"], failed: ["Consulta falhou; pendência mantida", "bad"], not_related: ["Não relacionada à fonte de cursos", "muted"],
  not_consulted: ["Fonte ainda não consultada", "muted"]
};
const KIND_GROUPS = [
  ["unit_courses", "Cursos listados por unidade"], ["unit_areas", "Áreas dos cursos por unidade"], ["contact", "Endereço e contato das unidades"],
  ["structure", "Estrutura do portal (filtros e matrícula)"], ["offer", "Modalidades"], ["requirements", "Requisitos de ingresso"], ["volatile", "Valores e vagas (dado volátil, não falado pelo robô)"]
];

function stamp(value, withTime = true) {
  if (!value) return "—";
  const date = new Date(value.length === 10 ? `${value}T12:00:00` : value);
  if (Number.isNaN(date.getTime())) return value;
  return withTime && value.length > 10 ? date.toLocaleString("pt-BR") : date.toLocaleDateString("pt-BR");
}

function chip(value, label, tone = "") {
  return el("li", { class: `stat-chip${tone ? ` ${tone}` : ""}` }, el("strong", { text: String(value) }), el("span", { text: label }));
}

function badge(label, tone) {
  return el("span", { class: `badge ${tone}`, text: label });
}

export function initKnowledgePanel() {
  const card = document.querySelector("#knowledge-card");
  if (!card) return { render() {}, refreshPortal() {} };
  const state = { status: null, portal: null, recordsOpen: false, pendingOpen: false, message: "" };
  const $ = (selector) => document.querySelector(selector);

  // ------------------------------------------------------------------ estatísticas da base
  function renderStats() {
    const list = $("#knowledge-stats");
    list.replaceChildren();
    const k = state.status;
    if (!k || !k.loaded) return;
    const by = k.by_status;
    list.append(chip(k.entries, "entradas"), chip(by.verified, "verificadas", "ok"), chip(by.review, "a confirmar", by.review ? "warn" : ""),
      chip(by.stale, "datadas ou vencidas", by.stale ? "warn" : ""), chip(by.pending, "pendentes", by.pending ? "warn" : ""));
  }

  // ------------------------------------------------------------------ fonte oficial
  async function refreshPortal() {
    try {
      state.portal = await api("/api/knowledge/portal");
    } catch {
      state.portal = null;
    }
    renderPortal();
    renderPending();
  }

  async function consult(force = false) {
    const button = $("#portal-refresh");
    button.disabled = true;
    state.message = "Consultando a página oficial (respeitando o robots.txt)…";
    renderPortalStatus();
    try {
      const result = await api("/api/knowledge/portal/refresh", { method: "POST", body: { force } });
      state.portal = result.portal;
      state.message = { extracted: `Consulta concluída: ${result.detail}`, cache: `Dados ainda válidos até a próxima revisão. ${result.detail}`,
        too_soon: result.detail, failed: `Falha na consulta: ${result.detail} As informações anteriores e as pendências foram mantidas.` }[result.outcome] || result.detail;
      state.canForce = result.outcome === "cache";
    } catch (error) {
      state.message = error.message;
    } finally {
      button.disabled = false;
    }
    renderPortal();
    renderPending();
  }

  async function decide(recordId, decision) {
    try {
      const result = await api(`/api/knowledge/portal/records/${encodeURIComponent(recordId)}/${decision}`, { method: "POST" });
      state.portal = result.portal;
      state.message = decision === "approve" ? "Registro confirmado pelo operador." : "Registro rejeitado.";
    } catch (error) {
      state.message = error.message;
    }
    renderPortal();
    renderPending();
  }

  function renderPortalStatus() {
    const portal = state.portal;
    const line = $("#portal-status");
    line.replaceChildren();
    if (state.message) line.append(document.createTextNode(state.message + " "));
    else if (portal && portal.available) {
      line.textContent = `Consultada em ${stamp(portal.consulted_at)} · próxima revisão em ${stamp(portal.next_review, false)}${portal.due ? " (vencida)" : ""} · ${portal.offerings} turma(s) lidas · ${portal.records.length} registro(s) organizados`;
    } else if (portal) line.textContent = portal.error ? `Última consulta falhou: ${portal.error}` : "Ainda não consultada. Use CONSULTAR FONTE para pesquisar a página oficial.";
    if (state.canForce) {
      line.append(el("button", { type: "button", class: "link-button", onclick: () => { state.canForce = false; consult(true); } }, "Forçar nova consulta"));
    }
  }

  function renderPortal() {
    const portal = state.portal;
    const section = $("#portal-source");
    if (!portal || !portal.source) {
      section.hidden = true;
      return;
    }
    section.hidden = false;
    const source = portal.source;
    $("#portal-source-name").textContent = source.name;
    const meta = $("#portal-meta");
    meta.replaceChildren(chip(source.category, "categoria"), chip(source.institution, "instituição"), chip("Fonte oficial", "tipo", "ok"), chip(source.freshness === "volatile" ? "dado volátil" : source.freshness, "atualidade"));
    const link = $("#portal-url");
    link.href = source.url;
    link.textContent = source.url;
    renderPortalStatus();
    const notice = $("#portal-security");
    notice.hidden = !portal.security_notice;
    notice.textContent = portal.security_notice ? `Atenção: ${portal.security_notice}` : "";
    const toggle = $("#portal-toggle");
    toggle.setAttribute("aria-expanded", String(state.recordsOpen));
    toggle.textContent = state.recordsOpen ? "Ocultar informações extraídas" : "Ver informações extraídas";
    toggle.disabled = !portal.available;
    renderRecords();
  }

  function renderRecords() {
    const box = $("#portal-records");
    box.hidden = !state.recordsOpen || !state.portal || !state.portal.available;
    box.replaceChildren();
    if (box.hidden) return;
    const portal = state.portal;
    const counts = portal.counts || {};
    box.append(el("ul", { class: "stat-chips" },
      ...Object.entries(RECORD_STATUS).filter(([key]) => counts[key]).map(([key, [label, tone]]) => chip(counts[key], label.toLowerCase(), tone === "info" ? "" : tone))));
    const pendingTopics = Object.fromEntries((state.status ? state.status.pending_items : []).map((p) => [p.id, p.topic]));
    for (const [kind, title] of KIND_GROUPS) {
      const records = portal.records.filter((r) => r.kind === kind);
      if (!records.length) continue;
      box.append(el("details", { class: "event-category", open: records.some((r) => r.status === "divergent") },
        el("summary", { text: `${title} (${records.length})` }),
        ...records.map((record) => {
          const [label, tone] = RECORD_STATUS[record.status] || [record.status, "muted"];
          const related = (record.pending_ids || []).map((id) => pendingTopics[id]).filter(Boolean);
          return el("article", { class: `event-item ${tone}`, id: `rec-${record.id}` },
            el("div", { class: "item-head" }, el("strong", { text: record.title }), badge(label, tone), record.volatile ? badge("Volátil", "muted") : null),
            el("p", { class: "item-content", text: record.content }),
            record.update_proposal ? el("p", { class: "item-content proposal", text: `Nova versão encontrada em ${stamp(record.update_proposal.consulted_at)}: ${record.update_proposal.content}` }) : null,
            el("p", { class: "event-meta", text: `Origem: ${portal.source.url} · consultada em ${stamp(record.consulted_at)} · próxima revisão ${stamp(record.next_review, false)}${record.approved_by ? ` · aprovada por ${record.approved_by === "operator" ? "operador" : record.approved_by}` : ""}${record.note ? ` · ${record.note}` : ""}` }),
            related.length ? el("p", { class: "event-meta", text: `Pendências relacionadas: ${related.join("; ")}` }) : null,
            el("div", { class: "item-actions" },
              record.status !== "confirmed" || record.update_proposal
                ? el("button", { type: "button", class: "button-secondary", onclick: () => decide(record.id, "approve") }, record.update_proposal ? "Aceitar atualização" : "Confirmar") : null,
              record.status !== "rejected" ? el("button", { type: "button", class: "button-secondary", onclick: () => decide(record.id, "reject") }, "Rejeitar") : null));
        })));
    }
  }

  // ------------------------------------------------------------------ pendências
  function renderPending() {
    const k = state.status;
    if (!k || !k.loaded) return;
    const items = k.pending_items || [];
    const total = items.length;
    $("#pending-number").textContent = String(total);
    $("#pending-number-text").textContent = String(total);
    const pill = $("#pending-pill");
    pill.classList.toggle("is-clear", total === 0);
    pill.querySelector("span").textContent = total ? "Em acompanhamento" : "Tudo em dia";
    const divergent = items.filter((p) => p.type === "divergence").length;
    const chips = $("#pending-chips");
    chips.replaceChildren(chip(total - divergent, "aguardando confirmação", total - divergent ? "warn" : ""), chip(divergent, "divergentes", divergent ? "warn" : ""),
      chip(k.by_status.stale, "entradas desatualizadas", k.by_status.stale ? "warn" : ""));
    const portal = state.portal;
    if (portal && portal.available) {
      const rc = portal.resolution_counts || {};
      chips.append(chip((rc.awaiting_validation || 0) + (rc.divergent || 0), "com informação na fonte oficial, a validar", "info"), chip(rc.resolved || 0, "resolvidas", rc.resolved ? "ok" : ""),
        chip(rc.unresolved || 0, "sem solução pela fonte"));
    }
    const toggle = $("#pending-toggle");
    toggle.setAttribute("aria-expanded", String(state.pendingOpen));
    toggle.textContent = state.pendingOpen ? "Ocultar pendências" : "Ver pendências";
    const list = $("#pending-list");
    list.hidden = !state.pendingOpen;
    list.replaceChildren();
    if (!state.pendingOpen) return;
    const resolutions = Object.fromEntries(((portal && portal.resolutions) || []).map((r) => [r.pending_id, r]));
    const order = { divergence: 0 };
    for (const item of items.slice().sort((a, b) => (order[a.type] ?? 1) - (order[b.type] ?? 1))) {
      const resolution = resolutions[item.id];
      const [resLabel, resTone] = resolution && resolution.status !== "not_related" ? RESOLUTION[resolution.status] || [resolution.status, "muted"] : [null, null];
      list.append(el("li", { class: `pending-item${item.type === "divergence" ? " divergence" : ""}` },
        el("div", { class: "item-head" }, el("strong", { text: item.topic }), badge(item.type === "divergence" ? "Divergente" : "Aguardando confirmação", item.type === "divergence" ? "bad" : "warn"), resLabel ? badge(resLabel, resTone) : null),
        el("p", { class: "item-content", text: item.reason }),
        resolution && resolution.status !== "not_related" ? el("p", { class: "event-meta", text: `Fonte oficial de cursos: ${resolution.note}` }) : null,
        item.action ? el("p", { class: "event-meta", text: `O que fazer: ${item.action}` }) : null,
        resolution && resolution.record_ids.length
          ? el("button", { type: "button", class: "link-button", onclick: () => { state.recordsOpen = true; renderPortal(); const target = document.getElementById(`rec-${resolution.record_ids[0]}`); if (target) { target.closest("details").open = true; target.scrollIntoView({ block: "center" }); } } }, "Ver informação extraída") : null));
    }
  }

  // ------------------------------------------------------------------ eventos
  $("#portal-refresh").addEventListener("click", () => consult(false));
  $("#portal-toggle").addEventListener("click", () => { state.recordsOpen = !state.recordsOpen; renderPortal(); });
  $("#pending-toggle").addEventListener("click", () => { state.pendingOpen = !state.pendingOpen; renderPending(); });

  return {
    render(status) {
      state.status = status;
      renderStats();
      renderPending();
    },
    refreshPortal
  };
}
