r"""Servidor de demonstração do Gerenciador de Eventos para os testes de navegador (SITES FICTÍCIOS, sem internet).

Uso:  .\.venv\Scripts\python.exe tests\e2e\serve_events_demo.py 8766
Sobe o SENAC BOT com uma pasta de eventos temporária e uma "internet de mentira" (tests/eventkb_helpers.FakeWeb) com os
sites de três eventos de teste. Nada é gravado em events/ nem consultado fora da máquina.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
os.environ["EVENTS_DIR"] = tempfile.mkdtemp(prefix="senac-events-")
os.environ["EVENT_AUTO_UPDATE"] = "false"
os.environ["GEMINI_API_KEY"] = ""  # teste determinístico: sem Gemini (respostas da base e do evento)

import uvicorn  # noqa: E402

import backend.main as main  # noqa: E402
from tests.eventkb_helpers import FakeWeb, gastronomia_site, profissoes_site, robotica_site  # noqa: E402

web = FakeWeb()
robotica_site(web)
gastronomia_site(web)
profissoes_site(web)
main.event_manager.researcher._fetcher_factory = web.factory()  # noqa: SLF001 - ponto de injeção para o teste
main.event_manager.researcher._resolver = None  # noqa: SLF001 - hosts fictícios (example.org) não resolvem no DNS
main.event_manager._last_run.clear()  # noqa: SLF001

if __name__ == "__main__":
    uvicorn.run(main.app, host="127.0.0.1", port=int(sys.argv[1]) if len(sys.argv) > 1 else 8766, log_level="warning")
