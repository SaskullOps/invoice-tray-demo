"""Command line: generate samples, process them, serve the review UI."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import pipeline
from .llm import make_llm
from .samples import generate

STATE_FILE = "extracted.json"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
REVIEW_FILE = "review.json"


def cmd_generate(args: argparse.Namespace) -> None:
    paths = generate(Path(args.samples))
    print(f"{len(paths)} documentos sintéticos en {args.samples}/")


def cmd_process(args: argparse.Namespace) -> None:
    llm = make_llm(fake=args.fake_llm, record=args.record)
    out = Path(args.out)
    endpoint = getattr(llm, "endpoint", "")
    print(f"Modelo: {llm.name}" + (f" en {endpoint}" if endpoint else ""))

    def progress(result: pipeline.Extracted) -> None:
        state = "error" if result.error else "ok"
        tokens = result.stats.get("prompt_tokens")
        extra = f" ({tokens} tokens de entrada)" if tokens else ""
        print(f"  {result.doc_id:<40} {state:<5} {result.seconds:>6.1f} s{extra}", flush=True)

    results = pipeline.extract_folder(Path(args.samples), llm, progress)
    pipeline.save_extracted(results, out / STATE_FILE)
    (out / REVIEW_FILE).unlink(missing_ok=True)
    evaluated = pipeline.evaluate(results, {})
    pipeline.write_outputs(evaluated, out)
    ready = sum(doc.status == "ready" for doc in evaluated)
    print(f"Listas para el ERP: {ready}  ·  A revisión: {len(evaluated) - ready}")
    print(f"Salida: {out}/ready.csv, {out}/exceptions.json")


def cmd_serve(args: argparse.Namespace) -> None:
    import uvicorn

    from .web import create_app

    app = create_app(Path(args.out), Path(args.samples), host=args.host)
    if args.host not in LOOPBACK_HOSTS:
        print(
            f"AVISO: la bandeja no tiene usuario ni contraseña y {args.host} no es una dirección "
            "local. Cualquiera que llegue a este puerto puede aprobar facturas.",
            file=sys.stderr,
        )
    print(f"Bandeja de revisión en http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="invoice-tray", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--samples", default="samples", help="folder with the PDFs")
        p.add_argument("--out", default="out", help="output folder")

    def process_flags(p: argparse.ArgumentParser) -> None:
        p.add_argument("--fake-llm", action="store_true", help="replay recorded model answers")
        p.add_argument(
            "--record", action="store_true", help="save real model answers as recordings"
        )

    def serve_flags(p: argparse.ArgumentParser) -> None:
        p.add_argument("--host", default="127.0.0.1")
        p.add_argument("--port", type=int, default=8000)

    generate_parser = sub.add_parser("generate", help="write the synthetic sample PDFs")
    common(generate_parser)
    generate_parser.set_defaults(func=cmd_generate)

    process_parser = sub.add_parser("process", help="extract, check and export")
    common(process_parser)
    process_flags(process_parser)
    process_parser.set_defaults(func=cmd_process)

    serve_parser = sub.add_parser("serve", help="start the review UI")
    common(serve_parser)
    serve_flags(serve_parser)
    serve_parser.set_defaults(func=cmd_serve)

    demo_parser = sub.add_parser("demo", help="generate + process + serve")
    common(demo_parser)
    process_flags(demo_parser)
    serve_flags(demo_parser)
    demo_parser.add_argument("--no-serve", action="store_true", help="stop after processing")
    demo_parser.set_defaults(func=cmd_demo)
    return parser


def cmd_demo(args: argparse.Namespace) -> None:
    cmd_generate(args)
    cmd_process(args)
    if not args.no_serve:
        cmd_serve(args)


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    args.func(args)
