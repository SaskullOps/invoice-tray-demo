# invoice-tray-demo

Supplier invoice PDFs go in, an ERP import file comes out, and every value the local model
returns has to quote the document it came from.

<p>
  <img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-blue?style=flat-square">
  <img alt="Python 3.12" src="https://img.shields.io/badge/python-3.12-3776AB?style=flat-square">
  <img alt="Data: synthetic only" src="https://img.shields.io/badge/data-synthetic-555?style=flat-square">
</p>

<p>
  <a href="#quick-start">Quick start</a> · <a href="#how-it-works">How it works</a> ·
  <a href="#configuration">Configuration</a> · <a href="#troubleshooting">Troubleshooting</a> ·
  <a href="#security-notes">Security</a>
</p>

<img src="docs/review-ui.png" width="100%" alt="Review queue in the browser with 11 synthetic supplier invoices: 4 marked ready for the ERP and 7 sent to review, each with its reason, such as a duplicate invoice number, a VAT amount that does not match its base, a wrong CIF control digit or a delivery note.">

Plain code checks each quote and runs the accounting checks. Anything doubtful goes to a
short review queue for a person.

> **Demo with synthetic data only.** Every company, person, tax id and IBAN is invented.
> **This tool never issues invoices.** It only receives and books supplier invoices, so it
> is outside the scope of Spain's invoicing-software rules (Verifactu). Do not extend it to issue
> invoices.

Typing a supplier invoice into an ERP by hand takes about 8 minutes in a
[case published by a software vendor](https://www.lido.app/es/automatizar-facturas) (a
distributor in Valencia, 150 invoices a month): open the PDF, copy the tax id, number, dates,
the base and VAT for each rate, any IRPF withholding and the IBAN, then check that the
numbers add up. Most invoices are routine. The point is to
do the routine ones automatically and show a person only the ones that need a decision,
together with the reason.

I wrote about how it was built [on my blog](https://alexguardiola.dev/en/blog/invoice-tray-to-erp-demo).

## Quick start

Requirements:

- [uv](https://docs.astral.sh/uv/) and `make`. uv reads `.python-version` and fetches
  Python 3.12 if it is not installed.
- For the real run only: [Ollama](https://ollama.com) listening on `localhost:11434`, with
  `qwen3:14b` pulled (a 9.3 GB download).

```bash
git clone --branch v0.1.0 https://github.com/alexguardiola/invoice-tray-demo.git
cd invoice-tray-demo
make demo-fake   # no model needed: replays recorded answers
```

`make demo-fake` writes 11 PDFs to `samples/`, processes them into `out/` and serves the
review UI at http://127.0.0.1:8000 until you press Ctrl+C. It does not open a browser. The
terminal output ends with:

```text
Listas para el ERP: 4  ·  A revisión: 7
Salida: out/ready.csv, out/exceptions.json
Bandeja de revisión en http://127.0.0.1:8000
```

The real run uses the local model (about 20-40 s per document on a 14B model, longer if part
of the model runs on the CPU). Its counts can differ from the recorded run (see
[measured numbers](#measured-numbers)).

```bash
ollama pull qwen3:14b
make demo
```

`make test` runs pytest and `make lint` runs ruff. Neither needs a model.

If port 8000 is already taken, the server stops with `address already in use` after the
documents are processed. Pick another port:

```bash
make demo-fake PORT=8001   # or: make demo PORT=8001
```

To clean up, stop the server with Ctrl+C, then delete the clone or run `git clean -fdX` inside
it. That removes only git-ignored files: `samples/`, `out/`, `.venv/` and the caches.

## How it works

```mermaid
flowchart LR
    A[PDF from the inbox] --> B[Text layer<br/>pypdf]
    B --> C[Local model<br/>JSON + verbatim quote per field]
    C --> D[Quote check in code<br/>quote in text? value in quote?]
    D --> E[Deterministic checks<br/>NIF/CIF, VAT, total, IRPF,<br/>IBAN, duplicates, type]
    E -->|all pass| F[out/ready.csv<br/>ERP import]
    E -->|any fails| G[out/exceptions.json<br/>review queue]
    G --> H[Review UI<br/>approve / fix / discard]
    H -->|fix re-runs the checks| E
```

1. Extract. `pypdf` reads the text layer. The model gets the text between
   `<document>` tags, marked as untrusted data, and returns JSON validated with Pydantic.
   Every field is `{"value": ..., "quote": ...}`.
2. Ground. Each quote must appear in the document text (ignoring case and spacing),
   and the value must be readable from that quote: the amount 104.58 must be written in
   `Cuota IVA 21 %: 104,58 €`, the date 2026-10-10 in `10/10/2026`. If either test fails, the
   value is set to null and the field is flagged. Confidence is computed in code from these
   results. The model is never asked how sure it is.
3. Check. Plain code, no model (see below).
4. Route. No blocking failure means `ready.csv`. Anything else goes to `exceptions.json`
   with its reasons. Review decisions are stored in `out/review.json`. A fix goes through
   the same checks again.

In the real recorded run, the model filled in a total, base and VAT for the delivery note.
That document has no totals, and the model quoted the column header `Importe` as the source.
The quote check discarded all three values.

The detail page shows the document text with every verified quote highlighted, the extracted
fields with their status, the checks, and a form to fix, approve or discard. The UI is in
Spanish.

<img src="docs/review-detail.png" width="100%" alt="Detail page of synthetic sample 11. On the left, the document text with verified quotes highlighted, including an Observaciones note that tells the system to set the total to 0 and change the IBAN. On the right, a banner sends it to review because the text holds two IBANs and instructions aimed at an automated system; below it, the extracted fields keep the real total of 560,84 euros and the real IBAN, each marked as a verified quote.">

### What is checked

Every failed check below sends the document to review, except a missing IBAN, which is only
a warning.

| Check | Rule |
|---|---|
| Tax id | NIF (DNI letter mod 23), NIE (X/Y/Z prefix), CIF (control digit or letter by entity type) |
| VAT per rate | `base × rate = VAT`, within 1 cent; rates outside 0/4/5/10/21 % are flagged |
| IRPF | `sum of bases × IRPF rate = withholding`, within 1 cent |
| Total | `bases + VAT − IRPF = total`, within 2 cents |
| Lines | item amounts add up to the taxable base |
| IBAN | ISO 13616 mod-97, plus the expected length for ES, PT, FR, DE, IT, GB and NL (other countries get mod-97 only) |
| IBAN count | more than one distinct IBAN in the text, written with spaces, dots, hyphens or nothing between the groups |
| IBAN position | the IBAN the model picked must be on a line labelled `IBAN` or `cuenta`, and must not come after an `Observaciones` heading |
| Spreadsheet formulas | an exported text value (or the file name) that starts with `=`, `+`, `-`, `@`, a tab or a carriage return |
| Duplicates | same supplier tax id and invoice number already seen in the batch |
| Required fields | supplier, tax id, number, issue date, total, VAT breakdown |
| Document type | delivery notes (`albarán`) are archived for matching, never booked |
| Quotes | any field whose quote failed the quote check |
| Embedded instructions | a short list of instruction phrases (for example "ignora las instrucciones" or "system prompt"); easy to evade, see [Prompt injection](#prompt-injection) |

### The samples

`invoice-tray generate` writes 11 PDFs and a `manifest.json` with the true values:

| File | Expected outcome |
|---|---|
| `01`–`04` | ready: VAT at 21 %, 21+10 %, 10+4 %, and a freelancer (NIE) with 15 % IRPF |
| `05` | duplicate of `01`, sent again |
| `06` | VAT amount does not match base × rate |
| `07` | CIF with a wrong control digit |
| `08` | invoice number missing |
| `09` | IBAN fails mod-97 |
| `10` | delivery note |
| `11` | an "Observaciones" note telling the system to set the total to 0, change the IBAN and skip review |

CIFs use the prefix `00`, which is not used for regular provincial registrations. The
freelancer in sample `04` has the all-zero NIE `X0000000T`. IBANs use bank code `9999`, which
is not a bank code in common use. All of them pass the check-digit algorithms. If a generated
value ever matches a real one, that is a coincidence. Use these values for testing only.

### Prompt injection

The model is told that the document is data and that instructions inside it must be
ignored. The design does not rely on the model obeying that:

- the model's answer is only data. Unknown keys such as `"approved": true` are dropped on
  parse, and nothing the model says can approve a document;
- every value must quote the document, so the model cannot report a value that is not printed
  there, and the tax id, VAT, total and IBAN checks run in code on those values. These checks
  are the real defence;
- the IBAN the model picked must sit on a line labelled `IBAN` or `cuenta` and must not come
  after an `Observaciones` heading, and a text with two or more distinct IBANs goes to a
  person;
- a short list of instruction phrases (`INJECTION_PATTERNS` in `src/invoice_tray/checks.py`)
  also sends a document to a person. Other wording gets past it, so it only catches obvious
  attempts.

Sample `11` shows it. With the real model, the recorded answer kept the real total
(560,84 €) and the real IBAN. The document still went to review because of the injected text.

## ERP import format (`out/ready.csv`)

UTF-8, `;` delimiter, `.` decimal separator, ISO dates, one row per invoice. Empty cells
mean the document has no such rate.

| Column | Content |
|---|---|
| `document_id` | source file name without extension |
| `supplier_tax_id` | NIF/NIE/CIF without spaces or `ES` prefix |
| `supplier_name` | the model's value, which must appear in its quote (case, accents and spacing are ignored) |
| `invoice_number` | the model's value, whose letters and digits must appear in its quote (punctuation, spaces and case are not compared) |
| `issue_date`, `due_date` | `YYYY-MM-DD` |
| `base_21`, `vat_21`, `base_10`, `vat_10`, `base_4`, `vat_4` | taxable base and VAT per rate |
| `base_other`, `vat_other` | any other rate (0 %, 5 %) |
| `irpf_rate`, `irpf_amount` | withholding rate (%) and amount (positive) |
| `total` | amount payable |
| `iban` | without spaces |
| `currency` | `EUR` |
| `review` | `auto` or `manual` (approved or fixed by a person) |
| `source_file` | PDF file name |

Most ERPs (A3, Sage, Holded, Odoo and others) can map a delimited file like this in their
import tool. The columns are kept flat on purpose.

A spreadsheet runs a cell that starts with `=`, `+`, `-`, `@`, a tab or a carriage return as a
formula. A document with such a text value goes to review (code `csv_formula`). If a person
approves it anyway, the text cell is written with a leading `'` (for example
`'=HYPERLINK(...)`), so a spreadsheet shows it as text. Amount columns are never prefixed.

`out/exceptions.json` lists each pending document with `reasons` (blocking) and `warnings`
(for example "no IBAN"), each as `{code, message}`.

## Configuration

`make demo` runs `uv run invoice-tray demo`: it generates the samples in `samples/`,
processes them into `out/` and starts the review UI. Each step can also run on its own:

```bash
uv run invoice-tray generate
uv run invoice-tray process [--fake-llm] [--record]
uv run invoice-tray serve [--port 8001]
```

`serve` reads what is already in `out/`, so after a real run you can reopen the UI without
calling the model again. `process` and `demo` delete `out/review.json`, which discards earlier
review decisions.

| Option | Default | Used by |
|---|---|---|
| `--samples` | `samples` | all commands |
| `--out` | `out` | all commands |
| `--fake-llm` | off | `process`, `demo` |
| `--record` | off | `process`, `demo`: overwrites the recordings in `src/invoice_tray/recordings/` |
| `--host` | `127.0.0.1` | `serve`, `demo`: see [Security notes](#security-notes) |
| `--port` | `8000` | `serve`, `demo` |
| `--no-serve` | off | `demo` |

The model endpoint is set with environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `INVOICE_TRAY_BASE_URL` | `http://localhost:11434/v1` | OpenAI-compatible endpoint |
| `INVOICE_TRAY_MODEL` | `qwen3:14b` | model name |
| `INVOICE_TRAY_API` | `auto` | `auto`, `ollama` or `openai` (see below) |
| `INVOICE_TRAY_API_KEY` | empty | sent as a bearer token in `openai` mode |

No other variable is read, so an `OPENAI_BASE_URL` or `OPENAI_API_KEY` set for other tools has
no effect. The first line of `process` names the model and the endpoint host, for example
`Modelo: ollama:qwen3:14b en localhost:11434`.

Ollama ignores `options` on its OpenAI-compatible `/v1` route, so the context window stays at
the server default (often 4096 tokens) and long documents are cut off without any error. In
`auto` mode, a base URL on port 11434 therefore uses Ollama's native `/api/chat`, which sets
`num_ctx` to fit the document, turns thinking off (`think: false`), constrains the answer to
the JSON schema, and fails loudly if the prompt still filled the window. Any other URL uses the
standard `/chat/completions` with `response_format: json_object` (and `/no_think` for qwen3
models).

## Tests

`make test` runs pytest without a model. Recorded answers from a real `qwen3:14b` run
live in `src/invoice_tray/recordings/`, and `make record` refreshes them. The tests
cover the check-digit algorithms, VAT and total arithmetic, IRPF, duplicates, IBAN, nulling of
unquoted or unsupported fields, the injection sample, the IBAN position and formula checks,
CSV columns and values, the review actions through the UI, and the host and origin checks.

## Measured numbers

One real run on my machine (RTX 4070 Ti with 12 GB, `qwen3:14b` through Ollama) took 548 s
for the 11 documents: between 34 and 67 s each, with 575 to 781 prompt tokens per document.
Another program held part of the GPU memory during that run, so Ollama put 23 % of the model
on the CPU, which slows it down.

That run gave 3 invoices ready and 8 to review, against 4 and 7 with the recordings. For
sample `04` the model returned the IRPF rate without a quote this time, so the quote check
discarded it and the invoice went to review. Real answers can differ from the recorded ones;
`--fake-llm` always replays the same recorded run.

## Troubleshooting

A model failure does not stop the run, and neither does an answer that cannot be read (for
example a number such as `1e400`). The document shows `error` in the progress list and goes
to review with the reason below, which is also in `out/exceptions.json` under the code
`model_error`.

| Symptom | Cause | Fix |
|---|---|---|
| `ERROR: [Errno 98] error while attempting to bind on address ('127.0.0.1', 8000): [errno 98] address already in use`, then `make: *** [Makefile:...: demo-fake] Error 3` | Another program is using port 8000 | `make demo-fake PORT=8001` (or `make demo PORT=8001`). After a real run, `uv run invoice-tray serve --port 8001` shows the results without calling the model again |
| Reason `Error del modelo: [Errno 111] Connection refused` on every document | Ollama is not running, or `INVOICE_TRAY_BASE_URL` points to the wrong host or port (the `Modelo:` line shows which one) | Start Ollama and run `make demo` again |
| Reason `Error del modelo: Client error '404 Not Found' for url 'http://localhost:11434/api/chat'` | The model named in `INVOICE_TRAY_MODEL` is not pulled | `ollama pull qwen3:14b`, or set `INVOICE_TRAY_MODEL` to a model you have |
| Reason `Error del modelo: <document id>: prompt truncated at num_ctx=<n>` | The prompt filled the context window that the client asked Ollama for | The window is sized from the document length in `_context_size` (`src/invoice_tray/llm.py`). Very long documents need a larger estimate |
| Reason `Respuesta del modelo no válida: ValidationError` | The answer did not match the schema, or held a number that is not finite, twice in a row (the client retries once) | With Ollama the schema constrains the answer. In `openai` mode only `json_object` is requested, so a weaker model can drift |
| Page `No se ha guardado nada` after a fix | A typed value could not be read, such as the date `31/02/2026` or the amount `abc` | Correct the value named in the message. Nothing was stored, and the document is unchanged |
| `Invalid host header` (HTTP 400) | The browser reached the UI under a host name other than `127.0.0.1`, `localhost` or the `--host` value | Open `http://127.0.0.1:<port>` |
| `Petición rechazada: no viene de esta página` (HTTP 403) | A POST came from another site, or from a client that sends neither `Sec-Fetch-Site` nor `Origin` | Use the buttons in the UI. A script must send `Origin: http://127.0.0.1:<port>` |

## Limits

- Text-layer PDFs only. Scanned paper needs OCR, which is not included. A free local
  OCR such as Tesseract or docTR could be added in front of the text step.
- Duplicates are detected within a batch. A real deployment would also check the ERP's
  supplier ledger.
- The quote check proves that a value is printed in the document. It does not prove that
  the value is in the right field. The arithmetic checks catch most of those mistakes.
- Single-page Spanish invoices in EUR. Other layouts and languages need their own samples
  and recordings.
- It never issues invoices.

## Security notes

- The review UI has no login and is meant for `127.0.0.1` only. Do not start it with
  `--host 0.0.0.0` or put it behind a shared proxy. `serve` prints a warning when `--host` is
  not a loopback address.
- Listening on loopback alone does not stop a web page you visit in the same browser from
  sending requests to the UI: it can post a form to `http://127.0.0.1:8000`, or use DNS
  rebinding to reach it under its own domain. So the UI answers only to the host names
  `127.0.0.1`, `localhost` and the `--host` value (anything else gets HTTP 400). It also
  refuses every POST (approve, fix, discard, undo) with HTTP 403 unless the browser marks it
  as sent from the UI's own pages: `Sec-Fetch-Site: same-origin` (or `none`), or, when that
  header is missing, an `Origin` equal to the UI's address. A request with neither header is
  refused.
- The UI loads no fonts, scripts or styles from other sites.
- With the defaults, document text goes only to the local Ollama. If you point
  `INVOICE_TRAY_BASE_URL` at a hosted provider, the full text of every document is sent there.
- Text inside a document is treated as data. Booking decisions come from the checks in code,
  never from the model's answer.

To report a vulnerability, see [SECURITY.md](SECURITY.md).

## License

MIT, see [LICENSE](LICENSE). A3, Sage, Holded, Odoo, Ollama and Qwen are trademarks of their
owners; this project is not affiliated with any of them.
