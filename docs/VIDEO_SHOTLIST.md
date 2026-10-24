# English demo video plan (target 2:35)

This is a recording plan, **not** a completed video or YouTube link. Record the actual local browser UI; retain the visible `REPLAY` label throughout. Do not imply a new provider call happens during filming.

| Time | On screen | English narration |
|---|---|---|
| 0:00–0:18 | Open local EdgeSRE Guardian page; show REPLAY badge | “A healthy process is not the same as a healthy checkout. EdgeSRE Guardian verifies the business route and lets an agent revise a failed repair.” |
| 0:18–0:37 | Incident and first observation | “In this historical R13 run, an isolated checkout service returned HTTP 503. The agent saw logs, metrics, current settings, and an action allowlist, but not the hidden fault threshold.” |
| 0:37–1:00 | First real model event; response ID and usage | “NVIDIA Nemotron on Nebius Token Factory diagnosed worker pressure and selected worker limit eight. This is a recorded real provider response, not a scripted live call.” |
| 1:00–1:21 | Safety Gate and first write | “The Safety Gate allowed the listed reversible setting. The executor applied it and made an independent HTTP check.” |
| 1:21–1:42 | HTTP 503; VERIFY_FAIL details | “Checkout still returned 503. The failed action, updated configuration, logs, and metrics became new evidence for the model.” |
| 1:42–2:05 | Second real model event; distinct action | “Nemotron reassessed the first hypothesis and selected request timeout 350 milliseconds, a different allowlisted action.” |
| 2:05–2:23 | Safety Gate, HTTP 200, final | “After the second write, checkout returned HTTP 200, so the loop stopped. If the bounded attempts had failed, the executor would have rolled back.” |
| 2:23–2:35 | Provider proof, limitations | “The trace includes two provider IDs and token usage. This is one isolated real recovery; the public page is replay only, and live requests require separate approval.” |

Before upload: verify a final cut below 3 minutes, show actual interaction on the target desktop browser, avoid copyrighted music and unapproved logos/assets, confirm captions, and upload a public YouTube link only with owner authorization.
