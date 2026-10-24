# Architecture and evidence boundaries

## Runtime

The existing R9/R12 incident lab starts an ephemeral `127.0.0.1` HTTP service and stores its configuration in a temporary file. The test service exposes `/health`, `/checkout`, `/metrics`, and `/logs`. Its hidden fault threshold is held in the lab object; it is not passed to the provider callback. A real Nemotron decision is parsed into one of `set_worker_limit`, `set_request_timeout_ms`, or `abstain`. The Safety Gate validates the exact action and a candidate value from the observation's allowlist, disallows non-progress and repeated failed actions, and never runs generated shell commands. After every allowed write, the service is checked over HTTP. A 503 produces a feedback record for the next decision. Exhaustion or unsafe output restores the original configuration.

The replay UI is a separate read-only presentation of the completed R13 run. It cannot make a Token Factory call. Its origin label and mode are hard-coded to `REPLAY` and the trace also records `live_calls_from_demo: 0`.

## Real R13 lineage

| Stage | Observed result |
|---|---|
| Model | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` on Nebius Token Factory |
| First request | Provider HTTP 200, response `chatcmpl-1e2c2f0e-fb43-466c-8021-7fceeacdf8a1`; action `set_worker_limit(8)` |
| First verification | `/health` 200, `/checkout` 503 |
| Feedback | Failed action, HTTP 503, timeout logs, metrics, and current config went to model |
| Second request | Provider HTTP 200, response `chatcmpl-5250427f-f80e-40dc-a99d-c72f519c5581`; action `set_request_timeout_ms(350)` |
| Second verification | `/health` 200, `/checkout` 200; stop |

This proves one scoped real-model, local-HTTP recovery. It does not prove repeated model reliability, arbitrary production remediation, hardware deployment, or financial posting of the estimated credit usage.

## Security

The public package contains no API key, owner authorization record, billing screenshot, card information, private browser state, or hidden R13 answer. The local server binds only loopback and serves an explicit allowlist of static files from `docs/`; GitHub Pages will also publish only `docs/`. The live CLI requires a distinct R14 approval record and signed-in trial readback before each request; it is disabled without them. Private artifacts must remain off the public repository and off any static host. Publishing a live service requires server-side identity, rate limits, cumulative token/cost enforcement, fresh trial checks, and a separate deployment review.

All model-visible actions remain allowlisted and reversible. Provider output is data, not executable code. The parser treats reasoning text as non-executable; only a valid final decision can be applied.
