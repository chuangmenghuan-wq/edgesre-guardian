# Devpost publication text — EdgeSRE Guardian

**Proposed track:** Best Apps and Agents. This agent delivers an end-to-end operational workflow for service owners. The Coding and Agentic Engineering track focuses on agents that write and test code; this project instead diagnoses telemetry and applies bounded service configuration repairs. We have not selected the Physical AI track because no physical hardware demonstration is claimed.

## Inspiration

An uptime dashboard can say a process is healthy while a business route is failing. Human responders must compare HTTP failures, metrics, logs, and configuration, choose a safe adjustment, and check whether the change actually worked. EdgeSRE Guardian makes that observe–act–verify loop explicit and auditable.

## What it does

EdgeSRE Guardian gives NVIDIA Nemotron a live incident observation and a short allowlist of reversible actions. The model chooses one diagnosis and one repair value. The executor applies only valid allowlisted configuration writes, independently checks `/health` and `/checkout`, and sends new failure evidence back to the model when a repair does not work. It stops on recovery or restores the original configuration when its bounded attempt budget is exhausted.

## How we built it

The agent uses `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` through the Nebius Token Factory serverless inference API. The isolated local HTTP lab models a checkout service and generates unknown faults. A strict parser validates model response identity, final decision JSON, finish reason, and token usage. A Safety Gate controls actions and values. A hash chained ledger records observations, decisions, writes, HTTP checks, and rollback.

The R13 real experiment made two genuine Token Factory requests. The first model action raised `worker_limit` to 8; checkout still returned HTTP 503. After receiving the failed action and fresh telemetry, Nemotron chose a different action, increasing `request_timeout_ms` to 350. Checkout then returned HTTP 200. Both provider response IDs and token usage are in the redacted trace. The R15 public interface replays this **historical** sequence and makes no live model calls.

## What we learned

The useful behavior was not the first guess. The decisive step was giving the model the failed HTTP result and current configuration and allowing a second bounded, different proposal. The lab also showed why success must be tied to an independent business route check, not the process health endpoint alone.

## Limitations and next steps

This is one real multi-step success in an isolated loopback lab, plus offline regression and new unseen fault tests. It is not a production reliability claim. The public judge test build is replay-only. A hosted live judge path requires a separately authorized cost budget, server-side access and quota controls, secret management, and deployment. Exact posted trial-credit debit remains pending Nebius Usage update.

## How judges can test it

Open the hosted static demo and use Play trace, Previous, Next, the speed selector, and any event in the ledger. Verify that the first model decision is `set_worker_limit(8)`, the first independent `/checkout` result is 503, the feedback event contains the failed action and new observation, the second model decision is `set_request_timeout_ms(350)`, both Safety Gate checks allow only listed reversible writes, and the final `/checkout` result is 200. Download the redacted trace for response IDs, token counts, and original evidence hashes. The page is clearly labeled REPLAY; it does not spend trial credits. The repository also has `python serve.py`, 54 offline tests, and a separately gated operator LIVE CLI. The latter is not offered as a public hosted endpoint or as a free anonymous model service.

## What changed during the competition

The early isolated incident lab and deterministic policy established reversible configuration writes, HTTP checks, and rollback. We then added the strict Nemotron response parser, provider identity and usage audit, failed-verification feedback loop, fresh unknown fault generation, budget gate, and the R13 two-call real-model recovery. R14–R15 added the redacted evidence export, interactive replay, browser visual acceptance, narrated screen recording, and a reviewable open-source package. These additions were made for this competition; the public replay does not turn deterministic offline tests into real model decisions.

## Feedback on the tools

Nebius Token Factory's OpenAI-compatible chat completions API made it possible to connect the existing bounded loop without provisioning a dedicated endpoint. Its response IDs, model identity, HTTP status, and token counts supported request-level evidence and cost estimates. NVIDIA Nemotron made the second, different proposal after receiving the failed HTTP check and updated telemetry; the useful behavior was the change of hypothesis after verification. The trial Stop usage after trial control helped bound risk. The Usage screen posted rounded values after a delay, so a more immediate per-request trial debit receipt would make cost-sensitive testing easier.

## Publication status

- Public repository: https://github.com/chuangmenghuan-wq/edgesre-guardian
- Working replay demo: https://chuangmenghuan-wq.github.io/edgesre-guardian/
- Public 166-second narrated browser video: https://www.youtube.com/watch?v=0MECamqwmpY
- Devpost project details and additional information are saved in the existing draft. The formal Rules/Terms checkbox and final Submit remain for the owner; the hackathon entry is not submitted.
