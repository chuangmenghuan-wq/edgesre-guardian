# EdgeSRE Guardian R40 — evaluator quick start

Open `index.html` through a static host to inspect saved real model evidence, then open `judge.html` to choose three saved offline simulations. To generate a fresh local HTTP lab run, use `python judge_server.py` and open `http://127.0.0.1:8765/`. In both lab modes the policy is offline; Nemotron is not called.

**Start with R37 L01.** The first two genuine Nemotron decisions partially improve the incident yet leave `/checkout` at 503. After two feedback cycles, the third model decision targets retry amplification. Independent `/health` and `/checkout` requests both return 200. The page is a replay of saved real API responses, with response IDs, request IDs, token counts and SHA-256 hashes; playback itself makes no API call.

**Then inspect R38 M02.** This impossible incident exposes a limitation: the model uses all four decisions without abstaining. The safety system restores the starting configuration, but the model's correct-refusal score is a failure. R38 totals 4/8 correct abstentions and 8/8 restorations. Select R38 M01 for a correct abstention.

**Audit every case.** The score table includes all 138 case IDs, including old `NOT_RUN` rows, R35's 18 truncation failures and R38's four missed refusals. The downloadable redacted receipt contains 238 new request records; private raw responses and hidden cases are excluded. R34, R36 and R37 share one model contract but use different sealed cases; their 55/56 repair success is a within-simulator distributional result, not production reliability or a paired gain over R17.

**Try the lab only as a mechanics test.** The hosted preview loads saved offline HTTP observations; the Python server can create a fresh local run. Both use an explicit deterministic policy and produce no new Nemotron decision. The local live route is disabled and returns 423. The submitted R15 public experience remains untouched.

The four judging dimensions are supported as follows: technical implementation by the strict contract, request receipts and chained HTTP evidence; product design by the visible decision loop and failure memory; potential impact by bounded reversible SRE changes; originality by model-directed replanning with explicit, separately scored abstention. The diverse abstention challenge currently falls short and blocks a broad safety claim.
