# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-10-29

### Added

- `invoice-tray` command with `generate`, `process`, `serve` and `demo` subcommands.
- 11 synthetic Spanish supplier invoices and delivery notes, with a `manifest.json` of
  expected outcomes.
- Extraction with a local model through Ollama's native `/api/chat`, or any
  OpenAI-compatible endpoint. Every field carries a verbatim quote that code checks against
  the document text.
- Deterministic checks for NIF/NIE/CIF, VAT per rate, IRPF, total, line sum, IBAN mod-97,
  duplicates, document type and embedded instructions.
- ERP import file `out/ready.csv` and review queue `out/exceptions.json`.
- Local review UI (in Spanish) to approve, fix or discard a document. A fix goes through the
  same checks again.
- Recorded `qwen3:14b` answers, so the tests and `--fake-llm` run without a model.

[0.1.0]: https://github.com/SaskullOps/invoice-tray-demo/releases/tag/v0.1.0
