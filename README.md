# EdgeSRE Guardian

**Track:** Best Apps and Agents, Nebius × NVIDIA Global AI Hackathon. **Public site mode: R13 REAL TRACE REPLAY.** The page does not call Nemotron at viewing time.

EdgeSRE Guardian is a bounded incident response agent. It observes an HTTP service, gives telemetry and an allowlist of reversible settings to NVIDIA Nemotron on Nebius Token Factory, executes one model proposed action through a Safety Gate, verifies the actual business route, and feeds a failed verification back to the model. It stops after recovery or rolls back when the bounded attempt budget is exhausted.

The R13 experiment contains **one real two-round recovery**. Nemotron first selected `set_worker_limit(8)`; the isolated `/checkout` endpoint still returned HTTP 503. The failed action, current configuration, HTTP status, metrics, and logs went into a second Token Factory request. Nemotron then selected `set_request_timeout_ms(350)`; `/checkout` returned HTTP 200. The two API responses consumed 749 prompt and 1,289 completion tokens in total. They are historical evidence, not a claim of production reliability.

## Run the judge test build

Requires Python 3.12 or later; the replay server and agent core use only the standard library. In a clean clone, from the repository root:

```bash
python serve.py
```

Open `http://127.0.0.1:8765/`. Use **Play trace**, **Previous**, **Next**, the speed selector, or click an event in the ledger. The UI displays every observed action, Safety Gate result, HTTP check, the feedback given to the second model call, and the two real provider response IDs and token counts. Download the redacted trace from the page. The same static files under `docs/` are intended for GitHub Pages. The page is **REPLAY only**: it makes **zero** Nebius calls and has no inference endpoint.

Run the inherited and new tests:

```bash
python -m unittest discover -s engine -p "test_*.py" -v
```

There are 54 tests in this source package. The additional R13 authorization gate tests belong to the private operator workspace and are not part of this public package. `test_r14_unseen.py` generates fresh worker, timeout, compound, and unrepairable cases. Its policy is explicitly **controlled offline test logic**, never presented as Nemotron reasoning.

## Architecture

```text
Loopback incident service → HTTP /health, /checkout, /metrics, /logs
                         → observation with current config + allowed actions
                         → Nebius Token Factory / NVIDIA Nemotron
                         → strict response parser → Safety Gate
                         → reversible local config write → independent HTTP verify
                                                     ├─ 200: stop, receipt
                                                     └─ 503: feedback → next model call
After exhausted budget or unsafe action: restore original configuration.
```

- `engine/r9_unseen_lab.py`: isolated loopback service, fault generator, bounded feedback loop, rollback, hash chained audit.
- `engine/r12_provider_parser.py`: separates final response content from reasoning, validates model identity, usage, finish reason, and structured action.
- `engine/r9_live_probe_once.py`: real Token Factory request adapter with fixed model, nonstreaming 1,024 token response cap, response/request IDs and usage capture.
- `engine/r14_live_runtime.py`: **operator-only, disabled by default** live orchestrator. It requires a distinct R14 Owner authorization record, per-call signed-in trial readbacks, a four-request limit, a US$0.005 estimated ceiling, an existing secret supplied at runtime, and durable no-retry reservations. No such authorization record or key is included in this package. Running it with no arguments performs a no-network preflight.
- `serve.py`: loopback-only, allowlisted static replay server. It cannot initiate model requests and does not serve `engine/` or `private/`.
- `docs/evidence/r13_public_trace.json`: field-allowlisted historical trace with original evidence hashes and exact real decisions, provider IDs, token usage, Safety Gate and HTTP results. The hidden fault threshold and all account data are excluded.

See [Architecture and security](docs/ARCHITECTURE.md) for the trust boundaries and evidence limits.

The narrated browser demonstration is 166 seconds and uses original screen footage; see [video credits](docs/VIDEO_CREDITS.md).

## LIVE operator path

The web UI intentionally has no LIVE button. An operator can run `python engine/r14_live_runtime.py` to see the offline, zero-request preflight. `--execute` requires a distinct Owner authorization record, a fresh signed-in trial/billing readback before and after each call, and a private API key supplied only to the process. The historical R13 authorization is not reusable. Never put a key or authorization record in the repository. The runner's private state is excluded by `.gitignore`, and `serve.py` serves only an explicit list of static files.

This source provides an auditable live path; it is not an unrestricted public inference service. A public real-time judge endpoint would additionally need its own explicit funding authorization, per-judge access control, server-side rate and cost quotas, secret management, and an approved deployment. The public static judge site is replay-only. Until a separately authorized live endpoint exists, judges can inspect the historical real trace and run the code locally, but cannot trigger free hosted live inference without a private key.

## R13 trace and reproducibility

The public trace carries SHA-256 values for the three R13 original artifacts and the full real-result file. Its event records retain the original event hashes, but redaction changes event data, so the **public trace by itself cannot recompute the private original event chain**. The independent verifier result was obtained before export. Reviewers can inspect the provider response IDs, request IDs, usage, model decisions, and HTTP transitions in the public trace. Full private source receipts remain with the owner.

The original experiment used two real Token Factory requests and a temporary local HTTP service. The model saw only observed HTTP, logs, metrics, configuration, and allowed actions; the hidden restoration threshold was withheld. The observed cost estimate from provider usage was US$0.0003543. Nebius's Usage display lagged, so the precisely posted trial-credit debit is unknown.

## Official submission status

The [public judge demo](https://chuangmenghuan-wq.github.io/edgesre-guardian/) and [166-second narrated video](https://www.youtube.com/watch?v=0MECamqwmpY) are **REPLAY** presentations of the recorded R13 incident. Viewing them does not make live model requests. This public repository is an open source test build; Devpost submission remains pending the owner's personal review and final acceptance of the official terms. The Best Apps and Agents positioning follows the [official challenge overview](https://nebiusglobalaihackathon.devpost.com/) and [rules](https://nebiusglobalaihackathon.devpost.com/rules). Keep the site available through the end of the official judging period, December 15, 2026.

## License

MIT, see [LICENSE](LICENSE). The owner confirmed the right to publish the included R9–R13 code and original visuals under MIT before this public release.
