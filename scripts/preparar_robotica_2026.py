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

# (categoria, título, conteúdo, palavras que o visitante costuma usar). Até 90 palavras cada, para serem faladas. Só o que as
# fontes oficiais ou o operador informaram; nada de programação por dia (ainda não divulgada).
ITEMS = [
    ("about", "Robótica 2026",
     "A Robótica 2026 é apresentada como o maior evento de robótica da América Latina. Reúne a Competição Brasileira de "
     "Robótica Petrobras, a etapa nacional da Olimpíada Brasileira de Robótica, a Mostra Nacional de Robótica, o "
     "Simpósio Brasileiro de Robóticas, o Workshop de Robótica na Educação e a Competição de Teses e Dissertações, "
     "com mais de 400 atividades.",
     ["o que é", "evento", "maior evento de robótica", "américa latina", "sobre o evento", "atividades"]),
    ("dates", "Datas do evento",
     "A Robótica 2026 acontece de 23 a 29 de novembro de 2026, no Centro de Convenções de João Pessoa. Nos dias 23 e 24 "
     "acontecem as competições. A visitação ao público é de 25 a 29 de novembro, das 9h às 21h.",
     ["quando", "data", "datas", "dias", "período", "quando acontece", "que dia", "começa", "termina", "onde e quando"]),
    ("location", "Local do evento",
     "A Robótica 2026 acontece de 23 a 29 de novembro, no Centro de Convenções de João Pessoa, na Rodovia PB-008, "
     "quilômetro 5, no bairro Cabo Branco.",
     ["onde", "local", "endereço", "como chegar", "como chego", "chego", "chegar", "lugar", "centro de convenções", "cabo branco",
      "onde acontece", "onde e quando"]),
    ("organization", "Organização",
     "Quem organiza a Robótica 2026 são voluntários de todo o Brasil. Entre os coordenadores está o presidente da "
     "RoboCup Brasil.",
     ["organiza", "organizador", "organizadores", "quem faz", "realização", "responsável", "promove", "robocup"]),
    ("exhibitors", "Participação do Senac Paraíba",
     "O que o Senac Paraíba faz na Robótica 2026: participa com um estande, onde você conhece o SENAC BOT, "
     "um robô virtual com inteligência artificial que conversa por voz.",
     ["senac", "estande", "stand", "participação", "o que o senac faz", "senac paraíba", "o que tem no estande"]),
    ("dates", "Entrada e visitação",
     "Você pode visitar a Robótica 2026 de 25 a 29 de novembro, das 9h às 21h. A entrada é gratuita. "
     "A programação de cada atividade é divulgada pela organização.",
     ["visitar", "visitação", "visita", "horário", "horários", "funcionamento", "aberto", "ingresso", "entrada", "entrar",
      "gratuita", "pagar", "pagar para entrar", "cobram", "custa", "grátis", "de graça", "quando posso visitar", "abre", "fecha",
      "preciso pagar", "precisa pagar"]),
    ("activities", "Competições",
     "As competições acontecem nos dias 23 e 24 de novembro. O evento reúne a Competição Brasileira de Robótica "
     "Petrobras e a etapa nacional da Olimpíada Brasileira de Robótica, entre outras atividades. "
     "A visitação do público é de 25 a 29.",
     ["competição", "competições", "campeonato", "torneio", "tem competição", "olimpíada", "equipes", "disputa"]),
    ("faq", "Siglas do evento",
     "No evento, CBR é a Competição Brasileira de Robótica Petrobras. OBR é a Olimpíada Brasileira de Robótica. "
     "MNR é a Mostra Nacional de Robótica. SBR é o Simpósio Brasileiro de Robóticas. WRE é o Workshop de Robótica "
     "na Educação, e CTDR é a Competição de Teses e Dissertações.",
     ["o que é a OBR", "o que é a CBR", "OBR", "CBR", "MNR", "SBR", "WRE", "CTDR", "sigla", "siglas", "o que significa", "diferença",
      "olimpíada brasileira de robótica", "mostra nacional de robótica"]),
    ("schedule", "Programação",
     "A Robótica 2026 tem mais de 400 atividades, incluindo palestras, workshops e apresentações científicas. A visitação ao público "
     "é de 25 a 29 de novembro, das 9h às 21h. A programação detalhada por dia, inclusive a de hoje, ainda será divulgada "
     "pela organização. Acompanhe pelo Instagram arroba cbrobotica e pelo canal Competição Brasileira de Robótica no YouTube.",
     ["programação", "agenda", "hoje", "palestra", "palestras", "oficinas", "workshop", "workshops", "o que tem", "atrações",
      "cronograma", "vai ter", "horário do evento"]),
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
        for category, title, content, keywords in ITEMS:
            current = existing.get((category, title))
            if current is None:
                print(f"{'[simulação] criaria' if dry else 'Criando'} item: {title}")
                if not dry:
                    call("POST", f"/api/events/{event_id}/items",
                         json={"category": category, "title": title, "content": content, "keywords": keywords})
            elif " ".join(current.get("content", "").split()) != content or list(current.get("keywords") or []) != keywords:
                print(f"{'[simulação] atualizaria' if dry else 'Atualizando'} item: {title}")
                if not dry:
                    call("PUT", f"/api/events/{event_id}/items/{current['id']}", json={"content": content, "keywords": keywords})
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
