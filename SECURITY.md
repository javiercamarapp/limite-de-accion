# Security policy

## Status

This is experimental software, not a production security boundary. The 0.1.x code is under active development. There is no security certification, support SLA or guarantee of containment. See [ESTADO.md](ESTADO.md) for the tested scope and unresolved boundaries.

Do not expose administrative library methods to untrusted callers. Do not run adversarial candidates with access to the host, Docker socket, credentials, reference answers or evaluator code. Offline library flags are not an OS sandbox.

## Report privately

Use [GitHub private vulnerability reporting](https://github.com/javiercamarapp/limite-de-accion/security/advisories/new) when it is available for this repository. If the form is unavailable, open an issue asking for a confidential reporting channel **without including the vulnerability or sensitive details**, and wait for a private channel before transmitting them.

Include the affected commit/version, environment, a minimal benign reproduction, expected and actual behavior, and impact. Use synthetic data. Never send credentials, private clinical data or details exposing unrelated systems.

No public disclosure deadline or response SLA is promised. No bug bounty or payment is offered. Coordinate disclosure with the maintainer; a public issue is not an appropriate place for an unmitigated vulnerability.

## Research boundaries

Test only the local project and systems you own or are explicitly authorized to assess. Do not access third-party accounts or systems, develop dangerous biological procedures, or claim that test results establish medical efficacy or containment of future AI systems.

## Known limitations

The local authority currently trusts its caller's identity and administrative channel. The process supervisor cannot contain a descendant that escapes its group and does not protect against a hostile process sharing the host identity. Atomic file writes are not a two-file transaction; storage failure or abrupt host termination can leave incomplete run state. These limits remain until independently verified implementations replace them.
