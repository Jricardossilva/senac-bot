r"""Atualiza o evento Robótica 2026 pela API do próprio SENAC BOT (local ou publicado), sem tocar no banco diretamente.

    .\.venv\Scripts\python.exe scripts\preparar_robotica_2026.py --url https://SEU-APP.onrender.com --token CODIGO_DO_OPERADOR
    (sem --url usa http://localhost:8000; sem --token usa a variável OPERATOR_TOKEN do .env)
    Adicione --simular para só mostrar o que seria alterado.

O que faz (idempotente: pode ser executado de novo):
- corrige o cadastro com o que as páginas oficiais informam (organização por voluntários/RoboCup Brasil; o Senac
  participa com estande) e define boas-vindas e perguntas sugeridas;
- atualiza ou cria os itens de conhecimento (sempre confirmados pelo operador, pois quem executa é o operador);
- cadastra as fontes oficiais e remove a fonte fictícia de exemplo, se existir.
A programação por dia NÃO é publicada pela organização ainda: o robô informa isso e remete aos canais oficiais."""
import argparse
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

EVENT_NAME = "Robótica 2026"
TOKEN_HEADER = "X-Operator-Token"

EVENT_FIELDS = {
    "description": "Maior evento de robótica da América Latina, com competições, mostra, palestras e workshops.",
    "organization": "Voluntários de todo o Brasil (RoboCup Brasil)",
    "venue": "Centro de Convenções de João Pessoa",
    "website": "https://robotica.robocup.org.br/",
    "program_url": "https://cbr.robocup.org.br/index.php/cronograma/programacao/",
    "welcome": "Olá! Eu sou o SENAC BOT, o robô virtual do Senac Paraíba na Robótica 2026. "
               "Pode me perguntar sobre o evento, sobre o Senac ou sobre tecnologia!",
    "suggested_questions": [
        "O que é a Robótica 2026?",
        "Onde e quando acontece?",
        "A entrada é gratuita?",
        "O que o Senac faz na Robótica 2026?",
        "Qual a diferença entre robótica e inteligência artificial?",
        "Como posso começar a estudar programação?",
    ],
}

# (categoria, título, conteúdo). Até 90 palavras cada, para serem faladas. Só o que as fontes oficiais ou o
# operador informaram; nada de programação por dia (ainda não divulgada).
ITEMS = [
    ("about", "Robótica 2026",
     "A Robótica 2026 é apresentada como o maior evento de robótica da América Latina. Reúne a Competição Brasileira de "
     "Robótica Petrobras, a etapa nacional da Olimpíada Brasileira de Robótica, a Mostra Nacional de Robótica, o "
     "Simpósio Brasileiro de Robóticas, o Workshop de Robótica na Educação e a Competição de Teses e Dissertações, "
     "com mais de 400 atividades."),
    ("dates", "Datas do evento",
     "A Robótica 2026 acontece de 23 a 29 de novembro de 2026. Nos dias 23 e 24 acontecem as competições. "
     "A visitação ao público é de 25 a 29 de novembro, das 9h às 21h."),
    ("location", "Local do evento",
     "A Robótica 2026 acontece no Centro de Convenções de João Pessoa, na Rodovia PB-008, quilômetro 5, "
     "no bairro Cabo Branco."),
    ("organization", "Organização",
     "O evento é organizado por voluntários de todo o Brasil. Entre os coordenadores está o presidente da RoboCup Brasil."),
    ("exhibitors", "Participação do Senac Paraíba",
     "O Senac Paraíba participa da Robótica 2026 com um estande, onde você pode conhecer o SENAC BOT, "
     "um robô virtual com inteligência artificial que conversa por voz."),
    ("visitor_info", "Entrada e visitação",
     "A entrada para visitar a Robótica 2026 é gratuita. A visitação ao público é de 25 a 29 de novembro, "
     "das 9h às 21h. A programação de cada atividade é divulgada pela organização."),
    ("schedule", "Programação",
     "A programação detalhada por dia ainda será divulgada pela organização. Para acompanhar, use os canais oficiais: "
     "o Instagram arroba cbrobotica e o canal Competição Brasileira de Robótica no YouTube."),
]

SOURCES = [
    ("https://robotica.robocup.org.br/", "site"),
    ("https://cbr.robocup.org.br/index.php/cronograma/", "site"),
    ("https://cbr.robocup.org.br/index.php/cronograma/programacao/", "program"),
]
FAKE_SOURCE_HOST = "robotica2026.example.org"


def load_env_token() -> str:
    token = os.environ.get("OPERATOR_TOKEN", "")
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if not token and env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("OPERATOR_TOKEN="):
                token = line.split("=", 1)[1].strip().strip('"').strip("'")
    return token


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--token", default="")
    parser.add_argument("--simular", action="store_true", help="só mostra o que seria feito")
    args = parser.parse_args()
    headers = {TOKEN_HEADER: args.token or load_env_token()}
    base = args.url.rstrip("/")
    dry = args.simular

    with httpx.Client(base_url=base, headers=headers, timeout=30) as http:
        def call(method: str, path: str, **kwargs) -> dict:
            response = http.request(method, path, **kwargs)
            if response.status_code >= 400:
                raise SystemExit(f"Falha em {method} {path}: {response.status_code} {response.text[:300]}")
            return response.json()

        events = call("GET", "/api/events")["events"]
        event = next((e for e in events if e["name"] == EVENT_NAME), None)
        if event is None:
            print(f"Evento '{EVENT_NAME}' não encontrado. Cadastre-o primeiro no Gerenciador de Eventos.")
            return 1
        event_id = event["id"]
        detail = call("GET", f"/api/events/{event_id}")
        print(f"Evento: {event_id} (estado: {detail['event'].get('state')})")

        if dry:
            print("[simulação] atualizaria o cadastro:", ", ".join(EVENT_FIELDS))
        else:
            call("PUT", f"/api/events/{event_id}", json=EVENT_FIELDS)
            print("Cadastro atualizado.")

        existing = {(i["category"], i["title"]): i for c in detail.get("categories", []) for i in c["items"]}
        for category, title, content in ITEMS:
            current = existing.get((category, title))
            if current is None:
                print(f"{'[simulação] criaria' if dry else 'Criando'} item: {title}")
                if not dry:
                    call("POST", f"/api/events/{event_id}/items", json={"category": category, "title": title, "content": content})
            elif " ".join(current.get("content", "").split()) != content:
                print(f"{'[simulação] atualizaria' if dry else 'Atualizando'} item: {title}")
                if not dry:
                    call("PUT", f"/api/events/{event_id}/items/{current['id']}", json={"content": content})
            else:
                print(f"Item já atualizado: {title}")

        known = {s["url"]: s for s in call("GET", f"/api/events/{event_id}").get("sources", [])}
        for url, kind in SOURCES:
            if url in known:
                continue
            print(f"{'[simulação] cadastraria' if dry else 'Cadastrando'} fonte oficial: {url}")
            if not dry:
                call("POST", f"/api/events/{event_id}/sources", json={"url": url, "kind": kind, "trust": "official"})
        for url, source in known.items():
            if FAKE_SOURCE_HOST in url:
                print(f"{'[simulação] removeria' if dry else 'Removendo'} fonte fictícia: {url}")
                if not dry:
                    call("DELETE", f"/api/events/{event_id}/sources/{source['id']}")

    print("Concluído. Confira em Operador > Gerenciador de Eventos e teste as perguntas no cartão de testes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
