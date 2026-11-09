r"""Gerenciador de Eventos no navegador (Edge headless): cadastro, pesquisa, validação, ativação, troca e isolamento.

Uso (servidor de demonstração em execução):
    .\.venv\Scripts\python.exe tests\e2e\serve_events_demo.py 8766
    .\.venv\Scripts\python.exe tests\e2e\browser_events.py http://127.0.0.1:8766/ [pasta_para_capturas]
Os eventos usados são FICTÍCIOS e identificados como SIMULAÇÃO.
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


def fill(b: Browser, name: str, value: str) -> None:
    b.js(f"(() => {{ const f = document.querySelector('#event-form').elements[{json.dumps(name)}]; f.value = {json.dumps(value)}; f.dispatchEvent(new Event('input', {{bubbles: true}})); }})()")


def shot(b: Browser, name: str) -> None:
    if SHOTS:
        time.sleep(0.6)
        open(os.path.join(SHOTS, name + ".png"), "wb").write(base64.b64decode(b.send("Page.captureScreenshot", format="png", captureBeyondViewport=True)["data"]))


def create_event(b: Browser, **values) -> None:
    b.click("#event-new")
    b.wait_for("document.querySelector('#event-dialog').open", 5)
    for key, value in values.items():
        fill(b, key, value)
    b.js("document.querySelector('#event-form').requestSubmit()")
    b.wait_for("!document.querySelector('#event-dialog').open", 5)


def research(b: Browser) -> None:
    b.js("[...document.querySelectorAll('#event-detail button')].find(x => x.textContent.includes('Pesquisar e preparar')).click()")
    b.wait_for("document.querySelector('#event-detail .event-job')?.textContent.includes('Última pesquisa')", 40)


def api(path: str, method: str = "GET", body=None):
    return b.js(f"fetch({json.dumps(path)}, {{method: {json.dumps(method)}, headers: {{'Content-Type': 'application/json'}}, body: {json.dumps(json.dumps(body)) if body is not None else 'undefined'}}}).then(r => r.json())")


def chat(message: str) -> dict:
    return api("/chat", "POST", {"message": message, "session_id": "e2e-events"})


b = Browser(BASE, 9508, fakes=False, width=1366, height=900)
try:
    b.js("window.confirm = () => true")
    R.check("a tela do visitante não tem o painel de eventos visível", b.js("document.querySelector('#events-card').closest('#operator').hidden"), True)
    R.check("sem evento ativo: eyebrow institucional", "CEP JOÃO PESSOA" in b.js("document.querySelector('#visitor-eyebrow').textContent"), True)
    default_welcome = b.js("document.querySelector('#messages .message p').textContent")

    b.click("[data-view=operator]")
    b.wait_for("document.querySelector('#events-card')", 5)
    R.check("painel do operador mostra o Gerenciador de Eventos", "GERENCIADOR DE EVENTOS" in b.js("document.querySelector('#events-card').innerText"), True)
    b.wait_for("document.querySelectorAll('#events-list .event-row').length >= 1", 10)
    R.check("lista traz o primeiro evento cadastrado (Robótica 2026), inativo", b.js("document.querySelector('#events-list').innerText.includes('Robótica 2026')") and not b.js("document.querySelector('#events-list .is-active')"), True)

    # --- cadastro parcial (só obrigatórios) de um evento novo, sem tocar no código
    create_event(b, name="Feira de Gastronomia SIMULAÇÃO", area="Gastronomia e alimentação", description="Feira fictícia de teste sobre culinária.",
                 start_date="2026-09-10", end_date="2026-09-12", website="https://feira-gastronomia.example.org/", organization="Organização Fictícia")
    b.js("document.querySelector('#event-form') && 0")
    b.wait_for("document.querySelector('#event-detail h3')?.textContent.includes('Gastronomia')", 8)
    R.check("evento cadastrado fica selecionado, em rascunho", "Rascunho" in b.js("document.querySelector('#event-detail').innerText"), True)
    R.check("ATIVAR EVENTO bloqueado antes de preparar", b.js("[...document.querySelectorAll('#event-detail button')].find(x => x.textContent.includes('Ativar evento')).disabled"), True)

    # --- cadastro inválido mostra erro amigável
    b.click("#event-new")
    b.wait_for("document.querySelector('#event-dialog').open", 5)
    fill(b, "name", "X"); fill(b, "area", "Y"); fill(b, "description", "Z"); fill(b, "start_date", "2026-05-10"); fill(b, "end_date", "2026-05-01")
    b.js("document.querySelector('#event-form').requestSubmit()")
    b.wait_for("document.querySelector('#event-form-error').textContent.length > 0", 5)
    R.check("data de término anterior à de início: erro amigável no formulário", "anterior" in b.js("document.querySelector('#event-form-error').textContent"), True)
    b.click("#event-form-cancel")

    # --- pesquisar e preparar
    research(b)
    text = b.js("document.querySelector('#event-detail').innerText")
    R.check("pesquisa concluída com resumo e fontes", "Última pesquisa" in text and "Fontes (1)" in text, True)
    R.check("conteúdo organizado por categoria", all(c in text for c in ("Datas e horários", "Programação")), True)
    full = b.js("document.querySelector('#event-detail').textContent")  # inclui as categorias recolhidas
    R.check("itens mostram a fonte e a aprovação automática", "Fonte: https://feira-gastronomia.example.org/" in full and "regra automática" in full, True)
    R.check("histórico registra a pesquisa", "Pesquisa" in b.js("document.querySelector('#event-detail details.event-section:last-of-type').innerText") or "Histórico" in text, True)
    shot(b, "events_detail")

    # --- validação humana: editar e rejeitar
    b.js("document.querySelectorAll('#event-detail .event-category').forEach(d => { d.open = true; })")
    b.js("[...document.querySelectorAll('#event-detail .event-item')].find(i => i.textContent.includes('oficina de massas'))?.querySelector('.item-actions button')?.click()")
    time.sleep(0.3)
    b.js("(() => { const ta = document.querySelector('#event-detail .item-editor textarea'); if (ta) { ta.value = 'Dia 11/09 às 16h: oficina de massas frescas e molhos no palco principal.'; ta.form.requestSubmit(); } })()")
    b.wait_for("document.querySelector('#event-detail').innerText.includes('16h')", 8)
    R.check("operador edita uma informação e ela fica confirmada por ele", "aprovada por operador" in b.js("document.querySelector('#event-detail').textContent"), True)

    # --- ativar
    b.js("[...document.querySelectorAll('#event-detail button')].find(x => x.textContent.includes('Ativar evento')).click()")
    b.wait_for("document.querySelector('#events-list .is-active')", 8)
    R.check("evento ativo aparece destacado na lista", "EVENTO ATIVO" in b.js("document.querySelector('#events-list .is-active').innerText"), True)
    reply = chat("Que horas é a oficina de massas frescas?")
    R.check("chat responde com a informação editada pelo operador", "16h" in reply["response"] and reply["source"] == "event", True)
    R.check("chat não usa o texto antigo (15h)", "15h" not in reply["response"], True)

    # --- visitante enxerga o contexto do evento
    b.click("[data-view=visitor]")
    b.wait_for("document.querySelector('#visitor-eyebrow').textContent.includes('GASTRONOMIA')", 8)
    R.check("visitante: eyebrow com o nome do evento", "FEIRA DE GASTRONOMIA" in b.js("document.querySelector('#visitor-eyebrow').textContent"), True)
    R.check("visitante: boas-vindas do evento", "Feira de Gastronomia" in b.js("document.querySelector('#messages .message p').textContent"), True)
    R.check("visitante: perguntas sugeridas do evento", any("programação" in q.lower() for q in b.js("[...document.querySelectorAll('#try-list q')].map(q => q.textContent)")), True)
    R.check("visitante não vê o painel nem dados internos do evento",
            not b.js("/observações|fonte:|aprovada por|rascunho|example\\.org/i.test(document.getElementById('visitor').innerText)"), True)
    shot(b, "events_visitor_active")

    # --- trocar de evento (Robótica 2026) sem misturar
    b.click("[data-view=operator]")
    b.wait_for("document.querySelectorAll('#events-list .event-row').length >= 3", 8)
    b.js("[...document.querySelectorAll('#events-list .event-row-main')].find(x => x.innerText.includes('Robótica 2026')).click()")
    b.wait_for("document.querySelector('#event-detail h3')?.textContent.includes('Robótica')", 8)
    b.js("[...document.querySelectorAll('#event-detail button')].find(x => x.textContent.includes('Editar')).click()")
    b.wait_for("document.querySelector('#event-dialog').open", 5)
    fill(b, "website", "https://robotica2026.example.org/")
    b.js("document.querySelector('#event-form').requestSubmit()")
    b.wait_for("!document.querySelector('#event-dialog').open", 5)
    research(b)
    b.js("[...document.querySelectorAll('#event-detail button')].find(x => x.textContent.includes('Ativar evento')).click()")
    b.wait_for("document.querySelector('#events-list .is-active')?.innerText.includes('Robótica')", 8)
    robotica = chat("Que horas é a oficina de robótica com Arduino?")
    R.check("Robótica 2026 ativo: responde sobre a oficina de robótica", "14h" in robotica["response"], True)
    gastro = chat("Que horas é a oficina de massas frescas?")
    R.check("Robótica 2026 ativo: não mistura informação da Feira de Gastronomia", "massas" not in gastro["response"] and "16h" not in gastro["response"], True)
    R.check("a Feira de Gastronomia foi desativada, com dados preservados", b.js("fetch('/api/events').then(r => r.json()).then(d => d.events.filter(e => e.active).length === 1 && d.events.find(e => e.name.includes('Gastronomia')).state === 'inactive' && d.events.find(e => e.name.includes('Gastronomia')).items_total > 5)"), True)

    # --- desativar volta ao institucional
    b.js("[...document.querySelectorAll('#event-detail button')].find(x => x.textContent.includes('Desativar')).click()")
    b.wait_for("!document.querySelector('#events-list .is-active')", 8)
    inst = chat("Onde fica o CEP João Pessoa?")
    R.check("sem evento ativo: conhecimento institucional continua", inst["source"] == "knowledge" and "Dom Pedro I" in inst["response"], True)
    b.click("[data-view=visitor]")
    b.wait_for("document.querySelector('#visitor-eyebrow').textContent.includes('CEP JOÃO PESSOA')", 8)
    R.check("visitante volta à experiência institucional", b.js("document.querySelector('#messages .message p').textContent") == default_welcome, True)

    # --- erros amigáveis
    err = b.js("fetch('/api/events/nao-existe').then(async r => [r.status, (await r.json()).detail])")
    R.check("evento inexistente: 404 com mensagem amigável", err, [404, "Evento não encontrado."])
    R.check("sem erros no console", b.real_errors(), [])
finally:
    b.close()
sys.exit(R.summary())
