# Security policy

This is a demo. It ships with synthetic invoices only, and it is not meant to process real
supplier documents as it stands.

## What to keep in mind

- The review UI has no login. It binds to `127.0.0.1` by default; keep it there. Do not run
  it with `--host 0.0.0.0` or put it behind a proxy that other people can reach.
- With the default settings, the document text goes only to the local Ollama at
  `localhost:11434`. If you set `OPENAI_BASE_URL` to a hosted endpoint, the full text of every
  document is sent to that provider.
- Text inside a document is treated as untrusted data. The checks that decide whether an
  invoice is booked run in code, and the model's answer cannot approve anything. Bypasses of
  that rule count as security issues.

## Supported versions

Only the latest release gets fixes.

## Reporting a vulnerability

Please report it privately through GitHub: open the repository's **Security** tab and choose
**Report a vulnerability**
([direct link](https://github.com/SaskullOps/invoice-tray-demo/security/advisories/new)).
Do not open a public issue for it.

This is a one-person project, so replies are best effort.
