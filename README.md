<div align="center">

# Límite de Acción
### A confident AI answer is not a permission slip.

**A local lab for testing AI answers, checking forecasts, and experimenting with explicit action boundaries.**

[Run the demo](#run-it-locally) · [Find a failure](#help-build-something-worth-trusting) · [What works today](#what-you-can-use-today) · [Guía en español](docs/USAGE.es.md)

**Make failures reproducible. Keep confidence separate from authority.**

</div>

---

## Why this exists

An AI system can produce a convincing answer and still be wrong. It can finish a task without satisfying the original request. A high benchmark score does not grant it permission to act.

**Límite de Acción turns those distinctions into code you can inspect and experiments you can repeat.**

We are starting small: deterministic evaluation, explicit uncertainty, and a transactional control experiment using a fictional calendar. The longer-term direction is a local-first laboratory where capability evaluation and external controls can be tested together—without requiring a proprietary AI API for the core.

**The invitation is global: don't take our word for it. Run it. Challenge it. Bring a reproducible counterexample.**

> [!IMPORTANT]
> **Experimental, not a production safety system.** This is not an enterprise release, an operating-system sandbox, or a guarantee of AI containment. A passing test is evidence about that test—not a certificate of safety.
>
> **Open source under the [MIT License](LICENSE).** Contributions are welcome: read [CONTRIBUTING.md](CONTRIBUTING.md). Report vulnerabilities through the [security policy](SECURITY.md), not public issue details.

## Run it locally

You need **Python 3.12** and [uv](https://docs.astral.sh/uv/). The recorded end-to-end checks ran on macOS; the experimental process supervisor uses POSIX APIs.

```bash
git clone https://github.com/javiercamarapp/limite-de-accion.git
cd limite-de-accion
uv sync --locked --extra dev
uv run --locked laboratorio demo-control
uv run --locked python -m pytest -q
```

**No AI API key, paid inference endpoint, or model download is needed for this demo.** Initial setup downloads Python dependencies. The core then runs locally.

The demo creates a temporary fictional calendar and checks three things:

```json
{
  "altered_intent_denied": true,
  "replay_same_receipt": true,
  "revoked_intent_denied": true,
  "human_approval_performed": false,
  "external_effects": false,
  "C1_T02_verified": false
}
```

*Selected fields from a verified run, not the complete output.* The experiment rejects changed intent, avoids repeating an already applied effect, and rejects a pending action after revocation. It does not authenticate a real human or operate a real calendar.

### Recover an uncertain action without sending it twice

```bash
uv run --locked laboratorio demo-durable-control --out runs/control-example
```

This second demo uses real local Unix sockets and two SQLite databases. It deliberately loses a response after a fictional event changes, reopens the controller, and reconciles the receipt **without re-sending the action**. The resulting sequence is `UNKNOWN → CONFIRMED`, with exactly one effect. A revoked follow-up is rejected. The output directory must be new and under trusted, non-shared parents.

It uses synthetic approvals and the same host UID: **this demo is not OS role separation or human authentication**. A separate, bounded Docker preflight checks three guest UIDs and 24 explicit permission/effect probes. See the [control and recovery guide](docs/CONTROL.es.md), including its resource profile, commands and limitations.

## What you can use today

| Component | What it does | What it does **not** prove |
|---|---|---|
| **Answer evaluation** | Scores JSON responses against deterministic references; rejects malformed input; keeps missing answers in the denominator | General intelligence, medical efficacy, or performance on a hidden benchmark |
| **Forecast evaluation** | Computes Brier scores for declared resolutions; keeps unresolved predictions unscored | That supplied evidence is authentic or a prediction was registered in advance |
| **Time-series baselines** | Tests last-value and seasonal baselines using only earlier observations | Prospective forecasting ability or pandemic prediction |
| **Local action experiment** | Binds an exact intent, declared actor, approval and resource version inside SQLite transactions | External authentication, a protected admin channel, or adversarial isolation |
| **Kernel-identified Unix channels** | Separates administrative and dispatcher method sets; obtains peer UID from the OS, never JSON | A real person's identity, dedicated VM isolation, or hostile-code containment |
| **Durable action controller** | Persists reservations and dispatch state; reconciles uncertain results by receipt query without replaying | Production service orchestration, authentication, or an external calendar integration |
| **Experimental process supervisor** | Bounds runtime and logs, handles interruption, and records explicit failure states | A security sandbox, hard OS resource quotas, or containment of escaping descendants |

The optional inference scripts require separately validated local MLX dependencies, weights and a manifest. A bounded local Qwen3-4B run was rechecked on September 19, 2026: **0/5 correct with the existing base profile, 3/5 with the existing typed profile**, on the same five public synthetic cases. Coverage was 4/5 and 5/5 respectively. This is a tiny, non-held-out smoke check—not training, a reliable capability estimate, or evidence of general improvement. No answers were executed as tools; no new weights or AI API were used.

See the [Spanish operating guide](docs/USAGE.es.md) for commands, file formats and failure semantics.

## One bug explains the philosophy

A review found that the evaluator could accept this wrong answer with **zero tolerance**:

```text
Expected: 100000000000000000000
Received: 100000000000000000001
Old result: correct
```

Mixing integers and floating-point arithmetic rounded away the difference. A separate reviewer reproduced it. A constructor added regression cases and replaced the lossy comparison with exact rational arithmetic. The coordinator repeated the reproduction and the tests before merging the fix.

**That is the kind of contribution we want: fewer false assurances, more executable evidence.**

The [regression is in the repository](tests/test_numeric_precision.py). So are tests for interruption, bounded logs, malformed inputs, persistence failures, revocation and replay.

## Evidence, not a green-badge promise

The recorded September 19, 2026 verification includes:

- **402 passing tests, no skips**, from the source tree and an extracted source distribution, including a packaging-link regression.
- **402 passing tests on Linux aarch64**, no skips, in a separate offline test container. Its trusted-code workspace permits native-extension execution; the permission preflight retains its separate `noexec` profile.
- Both control demos run from a clean wheel installation outside the source checkout; MIT license and source-distribution contents inspected.
- Real Unix/SQLite recovery demo: one effect, no uncertain-operation redispatch, revoked follow-up rejected.
- **24/24 benign Docker probes** across three guest UIDs after independent review and two fixes; source unchanged and owned container removed. This is not C1-T02 certification.
- Wheel construction, clean installation, and the installed demo run outside the repository.
- **189 passing tests from a fresh GitHub clone** at commit `36e34f8`.
- An 80-run benign process-cleanup check after fixing a macOS termination race.
- Secret scanning of published changes and Git history with no findings in those scans.

These are **recorded local results, not a continuously updated CI status**. GitHub Actions is disabled; no paid CI, hosting, or training service is provisioned by this repository. Re-run the checks on your own revision and environment.

Read the [verification record and limitations](ESTADO.md). A complete run is not necessarily a correct answer. A correct answer is never authorization.

## Help build something worth trusting

You do not need to train a bigger model to make a useful contribution.

| Your perspective | A useful first contribution |
|---|---|
| **Python engineer** | Reproduce an edge case; add a minimal failing test and a focused fix |
| **AI evaluation researcher** | Challenge a scoring assumption; propose benign tasks with independently checkable answers |
| **Security engineer** | Review authorization and process-lifecycle boundaries; explain what an experiment fails to establish |
| **Forecasting researcher** | Test chronology, resolution rules, leakage and baseline selection |
| **Technical writer or translator** | Make an experiment easier to reproduce; clarify a limit; help readers in another language |

### Bring a counterexample

For ordinary, non-sensitive bugs, [open an issue](https://github.com/javiercamarapp/limite-de-accion/issues/new) with:

1. The exact commit, operating system and Python version.
2. The command and the smallest **synthetic** input that reproduces the problem.
3. Expected versus actual output.
4. Why the difference matters.

For a fix, open a focused pull request with the reproduction and test output. **Do not remove a failing test just to make the suite green.**

Do not post credentials, private data, harmful biological procedures, or exploit details that would expose other systems. Do not test systems you do not own or have permission to assess. Use [GitHub private vulnerability reporting](https://github.com/javiercamarapp/limite-de-accion/security/advisories/new) following [SECURITY.md](SECURITY.md); if that form is unavailable, request a private channel without publishing sensitive details.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the contribution workflow, testing expectations and MIT contribution terms.

## The next frontier

- [x] Local evaluation with explicit missing/invalid states.
- [x] Forecast scoring and chronological baselines.
- [x] Fictional transactional authorization and revocation experiment.
- [x] Bounded process supervision with failure regressions.
- [x] Kernel-identified Unix transport and durable no-replay reconciliation.
- [x] Benign three-UID Docker preflight with bounded resources and explicit limitations.
- [ ] Independently verified OS isolation and candidate/evaluator separation.
- [ ] Real authentication and protected administrative authority.
- [ ] Reproducible local-model integration and justified, evaluated adaptation.
- [ ] Independently held-out evaluation and prospective validation.
- [ ] Public-evidence observatory with provenance and explicit uncertainty.
- [ ] Operational interface, deployment, monitoring and recovery validation.
- [x] Public-launch documentation: MIT license, contribution guide and security-reporting policy.

These are **open work items, not shipped features or promised outcomes**. The project does not claim to prevent extinction, discover cures, enumerate every agent on the internet, or contain a future superintelligence.

## Help the right people find it

**Run one experiment before sharing an opinion.** Then help others investigate it:

- **Star** it if you want to follow evidence-first AI tooling—not as a safety endorsement.
- **Share a reproduction**, whether it succeeds or fails. A useful failure can be more valuable than a promotional post.
- **Send it to one evaluator, engineer or researcher** who will challenge the assumptions.
- **Contribute one precise improvement.** No artificial activity, manufactured benchmarks or engagement spam.

A short introduction you can adapt:

> A confident AI answer isn't permission to act. Límite de Acción is an experimental local lab for deterministic evaluation, forecast checks, and explicit action-control tests. No AI API key needed for the core demo. Try it, find a failure, and help make the evidence better.
> https://github.com/javiercamarapp/limite-de-accion

---

<div align="center">

**Don't help us look safer. Help us find out where we aren't.**

[Run the demo](#run-it-locally) · [Read the evidence](ESTADO.md) · [Find a bug](https://github.com/javiercamarapp/limite-de-accion/issues/new) · [Español](docs/USAGE.es.md)

</div>

Local operations: [Unix/SQLite commands and limits](docs/OPERATOR-CLI.es.md), via `python -m laboratorio.operator_cli`. This is a synthetic same-UID workflow, not human authentication or role isolation.

Experiment provenance: [versioned local manifests](docs/EXPERIMENT-REGISTRY.es.md), via `python -m laboratorio.experiment_registry`. Hashes are computed from actual files; missing/invalid artifacts remain explicit. Integrity is not authenticity, scientific validation, or authorization.
