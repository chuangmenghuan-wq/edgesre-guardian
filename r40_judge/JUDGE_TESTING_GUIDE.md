# R40 judge testing guide — unpublished candidate

## Mode labels

| Label | Meaning |
| --- | --- |
| REAL PROVIDER TRACE | Historical Nebius Nemotron response and request identifiers with a saved SHA-256 response hash. |
| RECORDED REPLAY | The home screen presents those historical decisions. No request is sent now. |
| OFFLINE SIMULATION | D01–D03 use a disclosed deterministic policy, not Nemotron. Static hosting presents saved runs; the local Python server can create fresh loopback HTTP runs. |
| LIVE NEMOTRON | Disabled in this public test build. The local live route returns HTTP 423. |

## Static preview or hosted candidate

Run `python -m http.server 8766` in the package directory and open `http://127.0.0.1:8766/`. Select a recorded incident and inspect its model action, provider ID, response hash, Safety Gate and HTTP result. Then open `/judge.html` and select each of the three public scenarios. The application checks the saved receipt's SHA-256 against `evidence/offline_index.json` before rendering. D01 shows `/checkout 503 → 200`; D02 shows `503 → 503`, abstention and restored configuration; D03 shows failed partial steps followed by `503 → 200`. Download the JSON receipt and verify the hash chain locally:

```bash
python -c "import json,sys; from public_integrity import verify_chain; x=json.load(open(sys.argv[1],encoding='utf-8')); print(verify_chain(x['incident']['events']))" edgesre-D02_PUBLIC_UNREPAIRABLE-receipt.json
```

The hosted mode is a **saved offline simulation**. Clicking a scenario does not start a fresh service or call the model. A static host can remain usable after the trial expiry, subject to its own availability.

## Fresh local Python run

Use `python judge_server.py --port 8765`, then browse to `http://127.0.0.1:8765/judge.html`. The same scenario button now executes a fresh isolated loopback HTTP lab. The status line says so. The provider remains unused. `/api/judge/status` reports three public case IDs. `/api/judge/run` accepts only those IDs. `/api/judge/live` returns HTTP 423 with `provider_calls_sent: 0`. The server binds only to `127.0.0.1` and makes bounded temporary configuration changes.

## Boundaries

R38 official correct abstention is 4/8; R39 blind remains NOT_RUN and repair gain NOT_MEASURED. The R34–R37 55/56 historical recovery cohort is not an R39 score. This package contains public fixtures and redacted evidence only. The private sealed cases, raw provider bodies and credentials are excluded. This candidate needs an authorized external publication and independent URL/availability check before it can satisfy the official working-URL submission requirement. It does not offer judge-triggered live inference; Nebius runtime implementation and actual prior calls must be evaluated from separately reviewable source and receipts.

[Official rules](https://nebiusglobalaihackathon.devpost.com/rules)
