# Contributing

Help us replace false assurances with reproducible evidence. Contributions from engineers, evaluators, forecasters and translators are welcome.

## Start locally

Use Python 3.12 and uv:

```bash
uv sync --locked --extra dev
uv run --locked python -m pytest -q
uv run --locked laboratorio demo-control
```

Tests are local; this repository does not require a paid API or provision CI/hosting. The process supervisor is POSIX-specific and was verified on macOS. Other environments need their own verification, not an assumed pass.

## A useful pull request

1. Explain one concrete problem or agreed feature, not a general rewrite.
2. Provide the smallest synthetic reproduction. For a bug, add a regression and show it detects the defect.
3. Keep existing expectations; do not remove or weaken tests to hide failures.
4. Run the relevant tests and full suite. Include commands and observed outputs, including failures and unverified areas.
5. Update user documentation when behavior changes. Separate execution success from answer correctness, and correctness from authorization.
6. Keep commits substantive and accurately attributed. Do not create empty commits, fake dates or misleading contribution activity.

For a larger architectural change, discuss its scope in an issue first. Do not ship a simulated integration as if it were a verified real one.

## Never commit

Credentials, .env files, private datasets, clinical data, reviewer identities/approvals, model weights, raw run outputs or secrets copied from logs. Use synthetic fixtures. Model and dataset licenses must be checked separately; the project's MIT license does not relicense third-party assets.

Report vulnerabilities through the [security policy](SECURITY.md), not public issues. No unauthorized testing or harmful biological procedures.

## License

The project is [MIT licensed](LICENSE). By submitting a contribution for inclusion, you agree that your contribution may be distributed under this project's MIT license. Submit only material you have the right to contribute, and identify any third-party licenses or notices that must be retained.

## Sharing

Share a reproducible experiment, a useful failure, or a focused improvement. Stars can help people find the project; they do not establish security or scientific validity. No spam, fabricated benchmarks or artificial activity.
