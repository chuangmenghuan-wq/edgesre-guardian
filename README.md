# EdgeSRE Guardian — R41 submission update candidate

**This directory is a local release candidate, not the currently published R15 repository.** The public R15 GitHub repository and Devpost submission remain unchanged until the Owner authorizes an update.

EdgeSRE Guardian is a bounded incident agent for an isolated HTTP checkout service. It sends observations and an allowlist of reversible actions to NVIDIA Nemotron through Nebius Token Factory, parses a proposed action, applies a Safety Gate, verifies `/checkout` over HTTP, feeds failure back to the model, and restores original settings on unsuccessful attempts. The historical real-provider experiments are recorded; the public judge interface does not call the provider when viewed.

## Judge entrances and evidence modes

| Entry | Mode | What it proves |
| --- | --- | --- |
| [R40 public judge site](https://edgesre-guardian-r40-judge.vercel.app/judge.html) | **OFFLINE SIMULATION** receipts | Select D01, D02, D03; inspect saved isolated HTTP outcomes, refusal or recovery, and receipt hashes. This is free of Nebius trial dependence. |
| [R40 recorded-incident page](https://edgesre-guardian-r40-judge.vercel.app/) | **REAL PROVIDER TRACE / RECORDED REPLAY** | Inspect redacted historical Nebius Nemotron IDs, request IDs, usage, decision, Safety Gate result, and independent HTTP check. Playback sends zero requests. |
| `r40_judge/judge_server.py` | Fresh **OFFLINE SIMULATION** | Locally executes the three public development scenarios against a new loopback HTTP service. Decisions come from a disclosed deterministic policy, not Nemotron. |
| `engine/r14_live_runtime.py` | Gated **LIVE NEMOTRON** code path | The operator-only code can POST to Token Factory after a distinct private Owner authorization, key, account verification, signed-in before/after trial readbacks, and request/cost reservations. No key or authorization is shipped. Public judges cannot trigger a free live call. |

## Reproduce the judge test build

Requires Python 3.12 or later and no third-party Python packages. From the repository root:

```bash
cd r40_judge
python judge_server.py --port 8765
```

Open `http://127.0.0.1:8765/` for historical replay and `http://127.0.0.1:8765/judge.html` for D01, D02, D03. This server binds only to loopback. `POST /api/judge/live` returns HTTP 423 with zero provider calls. In a second terminal, run `python -m unittest -v test_judge.py` from `r40_judge`. Run the inherited engine tests from the repository root with `python -m unittest discover -s engine -p "test_*.py" -v`.

The three selectable public scenarios are D01 (repairable database wait, saved `/checkout` 503→200), D02 (beyond the repair allowlist, 503→503 with abstention and restored configuration), and D03 (partial step fails, then a later step reaches 503→200). These are **offline-policy** outcomes. Select each scenario, inspect the before/after HTTP cards and timeline, expand raw observations, and download the hash-checked receipt.

For the same saved-receipt experience as the public static site, from the repository root run `python -m http.server 8766 --directory r40_judge` and open `http://127.0.0.1:8766/judge.html`. The static selector checks each receipt SHA-256 before display. See [R41 judge guide](R41_JUDGE_TESTING_GUIDE.md) and the original [R40 test guide](r40_judge/JUDGE_TESTING_GUIDE.md).

## Runtime reproducibility boundary

The public source contains an **executable Nebius Token Factory Runtime integration**: `engine/r9_live_probe_once.py` sends a nonstreaming POST to `https://api.tokenfactory.nebius.com/v1/chat/completions` for `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`, captures provider/request IDs and token usage, and passes the response to a strict parser. `engine/r14_live_runtime.py` connects that adapter to the bounded incident loop. The saved R13 real two-call recovery and later redacted provider receipts show actual historical calls; tests validate the adapter and safety behavior without sending new requests.

Run `python engine/r14_live_runtime.py` for a zero-network preflight. An authorized operator can use `python engine/r14_live_runtime.py --execute` only with the distinct R14 Owner authorization record, a server-side `NEBIUS_API_KEY`, verified account and billing flags, fresh signed-in trial/usage readbacks before and after each request, and the built-in four-request / US$0.005 estimated caps. The R13 authorization is not reusable. This CLI is a genuine Live path, but it is deliberately unavailable on the public judge site; viewing Replay or Offline Simulation does not call Nebius. Judges can inspect the code and receipts and run the public scenarios without a key or payment. Never put a key in a browser or commit it to Git.

## Evidence limits

R13 contains one real two-round recovery: the first Nemotron-selected action left `/checkout` at HTTP 503; after failure feedback, its second action reached HTTP 200. R17's **6/8** belongs to a separate earlier experiment and is not added to later cohorts. The historical R34/R36/R37 repair cohort is **55/56** independent HTTP 200 recoveries under its isolated simulator conditions. R38 official correct abstentions remain **4/8**; eight of eight original configurations were restored. R39 sealed blind evaluation is **NOT_RUN**; repair gain **NOT_MEASURED**. The three R40 judge scenarios are public development cases with offline policy decisions, not a Nemotron score or R39 retest. The real-provider request log is a local cross-version record, not a reconciled provider billing statement. No production service or NVIDIA edge hardware result is claimed.

The public R40 site needs no Nebius trial to remain usable after the November 22, 2026 trial expiry. Its future availability through December 15 depends on continued hosting and must be read back during judging. A free, judge-triggered Live endpoint has not been established.

## Source and license

The original R15 replay, `serve.py`, `docs/`, and `engine/` are retained. `r40_judge/` contains the exact R40 Source Build snapshot, including its code, public cases, receipts, and MIT license. R40 snapshot documentation that says “unpublished” predates the authorized independent R40 deployment; this README and [R41 judge guide](R41_JUDGE_TESTING_GUIDE.md) give the current entrance. No R29/R38/R39 private sealed cases, raw provider bodies, credentials, or hidden answers are part of this candidate. Root [LICENSE](LICENSE) is MIT.
