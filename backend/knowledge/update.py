"""CLI da base de conhecimento.

    python -m backend.knowledge.update                 consulta todas as fontes oficiais (com educação) e atualiza o estado
    python -m backend.knowledge.update --only pb-psg   consulta apenas as fontes indicadas
    python -m backend.knowledge.update --report        mostra o que está vencido, a confirmar, pendente e a saúde das fontes
    python -m backend.knowledge.update --ack pb-unidades   marca como revisada a mudança detectada em uma fonte
"""
import argparse
import logging
import sys
from pathlib import Path

from backend.knowledge.base import KnowledgeBase
from backend.knowledge.updater import DEFAULT_DELAY_SECONDS, Updater

DEFAULT_DIR = Path(__file__).resolve().parent.parent.parent / "knowledge"


def print_report(directory: Path) -> int:
    kb = KnowledgeBase.load(directory)
    status = kb.status()
    print(f"Base de conhecimento: {status['entries']} entradas (hoje: {status['today']}; última consulta: {status['last_consulted']})")
    print("Por categoria:", ", ".join(f"{k}={v}" for k, v in sorted(status["by_category"].items())))
    print("Situação:", ", ".join(f"{k}={v}" for k, v in status["by_status"].items()))
    for error in status["errors"]:
        print("ERRO:", error)
    if status["stale"]:
        print("\nVencidas (precisam de nova consulta):")
        for item in status["stale"]:
            print(f"  - {item['id']} (validade {item['valid_until'] or 'por idade'}): {item['title']}")
    print("\nFontes:")
    for source in status["sources"]:
        flag = "REVISAR" if source["needs_review"] else ("FALHA" if source["error"] else "ok")
        print(f"  [{flag:7}] {source['id']:28} última consulta: {source['last_checked'] or 'nunca'}"
              + (f" | {source['error']}" if source["error"] else ""))
    print(f"\nPendências registradas: {len(status['pending_items'])}")
    for item in status["pending_items"]:
        print(f"  - {item['id']}: {item['topic']}")
    return 1 if status["errors"] else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Atualiza a base de conhecimento a partir das fontes oficiais do Senac.")
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR, help="pasta knowledge/")
    parser.add_argument("--only", nargs="*", help="ids de fontes a consultar")
    parser.add_argument("--ack", nargs="+", help="ids de fontes cuja mudança já foi revisada")
    parser.add_argument("--report", action="store_true", help="apenas mostra o relatório da base")
    parser.add_argument("--dry-run", action="store_true", help="consulta mas não grava state.json nem snapshots de estado")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY_SECONDS, help="segundos entre requisições (mínimo 1)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    if args.report:
        return print_report(args.dir)
    updater = Updater(args.dir, delay=max(1.0, args.delay))
    if args.ack:
        done = updater.acknowledge(args.ack)
        print("Revisão registrada para:", ", ".join(done) or "(nenhuma fonte com versão registrada)")
        return 0
    print("Consultando fontes oficiais (respeitando robots.txt, 1 requisição a cada", max(1.0, args.delay), "s)...")
    results = updater.run(only=args.only, dry_run=args.dry_run)
    failed = 0
    for result in results:
        mark = {"new": "NOVA", "unchanged": "igual", "changed": "MUDOU", "dynamic": "dinâm", "failed": "FALHA", "skipped": "pulou"}[result.outcome]
        print(f"  [{mark:5}] {result.id:28} {result.detail}")
        failed += result.outcome == "failed"
    changed = [r.id for r in results if r.outcome == "changed" and "revisão" in r.detail]
    if changed:
        print("\nATENÇÃO: estas fontes mudaram. Revise o conteúdo oficial, atualize os JSON e depois use --ack:", ", ".join(changed))
    print(f"\nConcluído: {len(results)} fontes, {failed} falhas. Última versão válida preservada nas falhas.")
    return 0 if not failed else 2


if __name__ == "__main__":
    sys.exit(main())
