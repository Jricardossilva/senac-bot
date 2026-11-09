r"""Servidor de demonstração para o teste de navegador dos cartões da Base de Conhecimento.

Uso:  .\.venv\Scripts\python.exe tests\e2e\serve_knowledge_demo.py 8767
Trabalha numa CÓPIA TEMPORÁRIA de knowledge/ e de events/ (incluindo a última extração real do portal de cursos técnicos),
para que aprovar/rejeitar registros no teste não altere os dados do projeto. Não consulta a rede nem usa o Gemini.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
work = Path(tempfile.mkdtemp(prefix="senac-kb-"))
shutil.copytree(ROOT / "knowledge", work / "knowledge", ignore=shutil.ignore_patterns("snapshots"))
if (ROOT / "events").exists():
    shutil.copytree(ROOT / "events", work / "events")
os.environ["KNOWLEDGE_DIR"] = str(work / "knowledge")
os.environ["EVENTS_DIR"] = str(work / "events")
os.environ["EVENT_AUTO_UPDATE"] = "false"
os.environ["GEMINI_API_KEY"] = ""

import uvicorn  # noqa: E402

import backend.main as main  # noqa: E402

if __name__ == "__main__":
    uvicorn.run(main.app, host="127.0.0.1", port=int(sys.argv[1]) if len(sys.argv) > 1 else 8767, log_level="warning")
