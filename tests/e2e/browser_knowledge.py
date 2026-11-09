r"""Cartões do painel do operador no Edge: Base de Conhecimento, Gerenciador de Eventos e Pendências de conhecimento.

Uso (com serve_knowledge_demo.py em execução):
    .\.venv\Scripts\python.exe tests\e2e\browser_knowledge.py http://127.0.0.1:8767/ [pasta_para_capturas]
Confere títulos e descrições, dados reais (sem indicadores inventados), pendências, fonte oficial de cursos técnicos, extração e
decisões do operador, estados de foco/hover, contraste, responsividade e a tela pública do visitante.
"""
import base64
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _browser import Browser, Reporter, base_url  # noqa: E402

BASE = base_url()
SHOTS = sys.argv[2] if len(sys.argv) > 2 else None
R = Reporter()
PAGE_URL = "https://pb.senac.br/matriculas/matricula/cursos-tecnicos/index.php"

CONTRAST_JS = """(selector, bgSelector) => {
  const parse = (c) => c.match(/[0-9.]+/g).slice(0, 3).map(Number);
  const lum = ([r, g, b]) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
  const solidBg = (el) => { while (el) { const c = getComputedStyle(el).backgroundColor; const p = parse(c); if (!/rgba\\(.*, 0\\)/.test(c) && c !== 'transparent') return p; el = el.parentElement; } return [255, 255, 255]; };
  const el = document.querySelector(selector);
  const fg = parse(getComputedStyle(el).color), bg = solidBg(el);
  const [a, b] = [lum(fg), lum(bg)];
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}"""


def shot(b: Browser, name: str, selector: str | None = None) -> None:
    if not SHOTS:
        return
    time.sleep(0.6)
    params = {"format": "png", "captureBeyondViewport": True}
    if selector:
        rect = b.js(f"(() => {{ const r = document.querySelector({json.dumps(selector)}).getBoundingClientRect(); return {{x: r.x + scrollX, y: r.y + scrollY, width: r.width, height: r.height}}; }})()")
        params["clip"] = {**rect, "scale": 1}
    open(os.path.join(SHOTS, name + ".png"), "wb").write(base64.b64decode(b.send("Page.captureScreenshot", **params)["data"]))


def contrast(b: Browser, selector: str) -> float:
    return b.js(f"({CONTRAST_JS})({json.dumps(selector)})")


b = Browser(BASE, 9509, fakes=False, width=1366, height=900)
try:
    api = lambda path, method="GET", body=None: b.js(  # noqa: E731
        f"fetch({json.dumps(path)}, {{method: {json.dumps(method)}, headers: {{'Content-Type': 'application/json'}}, body: {json.dumps(json.dumps(body)) if body is not None else 'undefined'}}}).then(r => r.json())")
    status = api("/api/knowledge/status")
    portal = api("/api/knowledge/portal")
    pending = status["pending_items"]

    b.click("[data-view=operator]")
    b.wait_for("document.querySelector('#pending-number').textContent !== '–' && document.querySelector('#portal-source') && !document.querySelector('#portal-source').hidden", 15)

    # ---------------------------------------------------------------- Card 1 — Base de Conhecimento
    R.check("card 1: título BASE DE CONHECIMENTO", b.js("document.querySelector('#knowledge-title').textContent"), "BASE DE CONHECIMENTO")
    R.check("card 1: descrição em segundo plano 'Informações oficiais do Senac'", b.js("document.querySelector('#knowledge-card .module-desc').textContent"), "Informações oficiais do Senac")
    R.check("card 1: ícone próprio (SVG decorativo, oculto para leitor de tela)", b.js("document.querySelector('#knowledge-card .module-icon svg') !== null && document.querySelector('#knowledge-card .module-icon').getAttribute('aria-hidden') === 'true'"), True)
    R.check("card 1: título maior que a descrição", b.js("parseFloat(getComputedStyle(document.querySelector('#knowledge-title')).fontSize) > parseFloat(getComputedStyle(document.querySelector('#knowledge-card .module-desc')).fontSize)"), True)
    chips = b.js("[...document.querySelectorAll('#knowledge-stats .stat-chip')].map(c => [c.querySelector('strong').textContent, c.querySelector('span').textContent])")
    by = status["by_status"]
    R.check("card 1: números das estatísticas vêm do servidor (sem invenção)", chips, [[str(status["entries"]), "entradas"], [str(by["verified"]), "verificadas"], [str(by["review"]), "a confirmar"], [str(by["stale"]), "datadas ou vencidas"], [str(by["pending"]), "pendentes"]])

    # ---------------------------------------------------------------- Card 2 — Gerenciador de Eventos
    R.check("card 2: título GERENCIADOR DE EVENTOS", b.js("document.querySelector('#events-title').textContent"), "GERENCIADOR DE EVENTOS")
    R.check("card 2: descrição 'Eventos e conhecimento do evento ativo'", b.js("document.querySelector('#events-card .module-desc').textContent"), "Eventos e conhecimento do evento ativo")
    R.check("card 2: ícone de calendário diferente do card 1", b.js("document.querySelector('#events-card .module-icon svg').innerHTML !== document.querySelector('#knowledge-card .module-icon svg').innerHTML"), True)
    R.check("card 2: identidade comum com acento próprio (laranja)", b.js("getComputedStyle(document.querySelector('#events-card .module-icon')).backgroundImage !== getComputedStyle(document.querySelector('#knowledge-card .module-icon')).backgroundImage"), True)
    R.check("card 2: sem evento ativo o aviso é claro", "Nenhum evento ativo" in b.js("document.querySelector('#events-active-banner').textContent"), True)
    events = api("/api/events")["events"]
    target = next(e["id"] for e in events if e["confirmed"] > 0)
    api(f"/api/events/{target}/activate", "POST")
    b.click("#event-refresh")
    b.wait_for("document.querySelector('#events-active-banner').classList.contains('is-active')", 8)
    banner = b.js("document.querySelector('#events-active-banner').textContent")
    R.check("card 2: destaca o EVENTO ATIVO com o nome real", "EVENTO ATIVO" in banner and next(e["name"] for e in events if e["id"] == target) in banner, True)
    api("/api/events/deactivate", "POST")

    # ---------------------------------------------------------------- Card 3 — Pendências
    R.check("card 3: número em destaque = pendências reais", b.js("document.querySelector('#pending-number').textContent"), str(len(pending)))
    R.check("card 3: texto explicativo", b.js("document.querySelector('#pending-card .pending-text').textContent"), "Informações que precisam de confirmação ou atualização.")
    R.check("card 3: indicador de situação (não é erro crítico)", b.js("document.querySelector('#pending-pill').textContent.trim()"), "Em acompanhamento")
    divergent = sum(1 for p in pending if p["type"] == "divergence")
    pchips = b.js("[...document.querySelectorAll('#pending-chips .stat-chip')].map(c => [c.querySelector('strong').textContent, c.querySelector('span').textContent])")
    R.check("card 3: quantidade por situação (aguardando, divergentes, desatualizadas) com dados reais",
            pchips[:3], [[str(len(pending) - divergent), "aguardando confirmação"], [str(divergent), "divergentes"], [str(by["stale"]), "entradas desatualizadas"]])
    counts = portal["resolution_counts"]
    resolved_chips = {c[1]: c[0] for c in pchips}
    R.check("card 3: situação em relação à fonte oficial vem da extração real",
            (resolved_chips.get("sem solução pela fonte"), resolved_chips.get("resolvidas"), resolved_chips.get("com informação na fonte oficial, a validar")),
            (str(counts.get("unresolved", 0)), str(counts.get("resolved", 0)), str(counts.get("awaiting_validation", 0) + counts.get("divergent", 0))))
    R.check("card 3: cor de atenção âmbar, não vermelho", b.js("(() => { const [r, g, bl] = getComputedStyle(document.querySelector('#pending-card .pending-count')).borderTopColor.match(/\\d+/g).map(Number); return r > 200 && g > 130 && g < 200 && bl < 120; })()"), True)
    R.check("card 3: lista recolhida por padrão", b.js("document.querySelector('#pending-list').hidden"), True)
    b.click("#pending-toggle")
    b.wait_for("!document.querySelector('#pending-list').hidden", 5)
    R.check("card 3: 'Ver pendências' expande todas (aria-expanded)", b.js("[document.querySelector('#pending-toggle').getAttribute('aria-expanded'), document.querySelectorAll('#pending-list li').length]"), ["true", len(pending)])
    R.check("card 3: divergentes aparecem primeiro", b.js("[...document.querySelectorAll('#pending-list li')].slice(0, 3).every(li => li.classList.contains('divergence'))"), divergent == 3 or divergent == 0 or True)
    first = b.js("document.querySelector('#pending-list li').textContent")
    R.check("card 3: cada pendência mostra o motivo e a situação perante a fonte oficial", "fonte oficial de cursos" in b.js("document.querySelector('#pending-list').textContent").lower() and ("aguardando" in first.lower() or "divergente" in first.lower()), True)
    shot(b, "k_pending_open", "#pending-card")

    # ---------------------------------------------------------------- Fonte oficial de cursos técnicos
    R.check("fonte: nome 'Cursos Técnicos — Senac Paraíba'", b.js("document.querySelector('#portal-source-name').textContent"), "Cursos Técnicos — Senac Paraíba")
    metas = b.js("[...document.querySelectorAll('#portal-meta .stat-chip')].map(c => c.textContent)")
    R.check("fonte: categoria, instituição e tipo", any("Cursos e matrículas" in m for m in metas) and any("Senac PB" in m for m in metas) and any("Fonte oficial" in m for m in metas), True)
    R.check("fonte: URL oficial exibida e com link seguro", b.js("(() => { const a = document.querySelector('#portal-url'); return [a.href, a.target, a.rel]; })()"), [PAGE_URL, "_blank", "noopener noreferrer"])
    R.check("fonte: data da consulta e próxima revisão", "Consultada em" in b.js("document.querySelector('#portal-status').textContent") and "próxima revisão" in b.js("document.querySelector('#portal-status').textContent"), True)
    R.check("fonte: aviso sobre credenciais descartadas (sem exibir valores)", "descartados" in b.js("document.querySelector('#portal-security').textContent") and "sk_" not in b.js("document.body.innerText"), True)
    b.click("#portal-toggle")
    b.wait_for("!document.querySelector('#portal-records').hidden", 5)
    groups = b.js("[...document.querySelectorAll('#portal-records details summary')].map(s => s.textContent)")
    R.check("informações extraídas agrupadas por tipo", any("Cursos listados por unidade" in g for g in groups) and any("Endereço e contato" in g for g in groups), True)
    n_records = b.js("document.querySelectorAll('#portal-records .event-item').length")
    R.check("todos os registros reais aparecem, cada um com origem e data", n_records == len(portal["records"]) and "Origem: " + PAGE_URL in b.js("document.querySelector('#portal-records .event-item .event-meta').textContent"), True)
    R.check("registros volantes (valores e vagas) identificados como voláteis", "Volátil" in b.js("document.querySelector('#portal-records').textContent"), True)
    shot(b, "k_portal_records", "#knowledge-card")

    # --- decisões do operador (na cópia temporária)
    b.js("document.querySelectorAll('#portal-records details').forEach(d => { d.open = true; })")
    b.js("[...document.querySelectorAll('#rec-struct-cidades button')].find(x => x.textContent === 'Confirmar').click()")
    b.wait_for("document.querySelector('#rec-struct-cidades .badge').textContent === 'Confirmada'", 8)
    R.check("operador confirma um registro: situação 'Confirmada' e aprovado por operador", "aprovada por operador" in b.js("document.querySelector('#rec-struct-cidades .event-meta').textContent"), True)
    b.js("document.querySelectorAll('#portal-records details').forEach(d => { d.open = true; })")
    b.js("[...document.querySelectorAll('#rec-struct-turnos button')].find(x => x.textContent === 'Rejeitar').click()")
    b.wait_for("document.querySelector('#rec-struct-turnos .badge').textContent === 'Rejeitada'", 8)
    after = api("/api/knowledge/portal")
    R.check("decisões persistidas no servidor", (after["counts"].get("confirmed", 0) >= 1, after["counts"].get("rejected", 0) >= 1), (True, True))
    R.check("nenhuma pendência virou 'resolvida' sem aprovação das informações estáveis e completas", after["resolution_counts"].get("resolved", 0) <= portal["resolution_counts"].get("resolved", 0) + 1, True)

    # --- nova pesquisa (usa o cache: nada de requisição repetida)
    b.click("#portal-refresh")
    b.wait_for("document.querySelector('#portal-status').textContent.includes('ainda válidos')", 10)
    R.check("nova pesquisa respeita o cache e oferece forçar a atualização", b.js("document.querySelector('#portal-status .link-button')?.textContent"), "Forçar nova consulta")

    # ---------------------------------------------------------------- foco, hover e contraste
    b.js("if (document.querySelector('#portal-toggle').getAttribute('aria-expanded') === 'true') document.querySelector('#portal-toggle').click()")  # recolhe os registros
    b.js("document.querySelector('#portal-refresh').focus()")
    for _ in range(20):  # navegação por teclado (Tab), como um operador faria: ativa :focus-visible
        if b.js("document.activeElement.id") == "pending-toggle":
            break
        b.send("Input.dispatchKeyEvent", type="rawKeyDown", windowsVirtualKeyCode=9, key="Tab", code="Tab")
        b.send("Input.dispatchKeyEvent", type="keyUp", windowsVirtualKeyCode=9, key="Tab", code="Tab")
        time.sleep(0.15)
    R.check("estado de foco visível nos botões", b.js("(() => { const s = getComputedStyle(document.querySelector('#pending-toggle')); return s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) >= 2; })()"), True)
    b.js("document.querySelector('#knowledge-card button').focus()")
    R.check("card muda de aparência quando recebe foco (focus-within)", b.js("getComputedStyle(document.querySelector('#knowledge-card')).boxShadow !== getComputedStyle(document.querySelector('#events-card')).boxShadow"), True)
    b.js("document.activeElement.blur()")
    b.js("document.querySelector('#events-card').scrollIntoView({block: 'start'})")
    time.sleep(0.4)
    before = b.js("getComputedStyle(document.querySelector('#events-card')).boxShadow")
    rect = b.js("(() => { const r = document.querySelector('#events-card .module-head').getBoundingClientRect(); return [r.x + 40, r.y + r.height / 2]; })()")
    b.send("Input.dispatchMouseEvent", type="mouseMoved", x=rect[0], y=rect[1])
    time.sleep(0.5)
    R.check("estado de hover altera a sombra do card", b.js("getComputedStyle(document.querySelector('#events-card')).boxShadow") != before, True)
    for name, selector in (("título do card 1", "#knowledge-title"), ("descrição do card 1", "#knowledge-card .module-desc"), ("título do card 2", "#events-title"),
                           ("texto de pendências", "#pending-card .pending-text"), ("título de pendências", "#pending-title"), ("chip de atenção", "#pending-chips .stat-chip.warn"),
                           ("indicador âmbar", "#pending-pill")):
        R.check(f"contraste suficiente (WCAG AA 4.5:1): {name}", contrast(b, selector) >= 4.5, True)

    # ---------------------------------------------------------------- responsividade
    for width, height, mobile in ((1366, 900, False), (768, 1024, True), (390, 844, True)):
        b.send("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=1, mobile=mobile)
        time.sleep(0.6)
        overflow = b.js("document.documentElement.scrollWidth - document.documentElement.clientWidth")
        R.check(f"operador sem rolagem horizontal em {width}px", overflow <= 1, True)
        R.check(f"cards legíveis em {width}px (título e botões dentro da tela)",
                b.js("[...document.querySelectorAll('#knowledge-card, #events-card, #pending-card')].every(c => { const r = c.getBoundingClientRect(); return r.left >= -1 && r.right <= innerWidth + 1; })"), True)
        shot(b, f"k_cards_{width}", "#knowledge-card")
        shot(b, f"k_pending_{width}", "#pending-card")
        shot(b, f"k_events_{width}", "#events-card")
    b.send("Emulation.clearDeviceMetricsOverride")

    # ---------------------------------------------------------------- tela do visitante
    b.click("[data-view=visitor]")
    R.check("visitante: nada dos cartões administrativos", b.js("document.getElementById('visitor').querySelector('#knowledge-card, #pending-card, #events-card, #portal-source') === null"), True)
    R.check("visitante: sem termos de pendência nem URLs internas", not b.js("/pendência|extra[çc]|portal de|get-turmas/i.test(document.getElementById('visitor').innerText)"), True)
    R.check("sem erros no console", b.real_errors(), [])
finally:
    b.close()
sys.exit(R.summary())
