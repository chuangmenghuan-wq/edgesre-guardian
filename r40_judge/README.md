# EdgeSRE Guardian R40 — independent judge test candidate

This is an unpublished release candidate derived from the R39 Judge Test Build. It has two evidence modes:

1. `index.html` is **RECORDED REPLAY** of saved real Nebius Nemotron decisions from R28–R38. Provider IDs, request IDs, response hashes and loopback HTTP outcomes are included in a redacted public receipt. Playback sends zero model requests.
2. `judge.html` lets a judge select D01 recovery, D02 refusal and rollback, or D03 failed partial step then recovery. On a static host it loads SHA-256 checked **OFFLINE SIMULATION** receipts created by the R39 local Python lab. On the included Python server it instead runs fresh loopback HTTP checks. Decisions in both variants come from a disclosed deterministic development policy; **MODEL NOT RUN**.

For a fresh local run, use Python 3.12 or later; no pip packages are needed:

```bash
python judge_server.py --port 8765
python -m unittest -v test_judge.py
```

Open `http://127.0.0.1:8765/` and `http://127.0.0.1:8765/judge.html`. To preview the static-host version, run `python -m http.server 8766` in this folder and open `http://127.0.0.1:8766/judge.html`.

`POST /api/judge/live` returns HTTP 423 before provider dispatch. There is no API key in the browser or package. The R34 contract demonstrates the frozen model interface, while the separately retained private runner contains the actual Nebius Token Factory call implementation. This published candidate does not offer a fresh Nebius call to the public. R38 abstention remains **4/8** and R39 blind evaluation is **NOT_RUN**.

The static demo remains usable without the Nebius trial, which expires November 22, 2026, but no hosted URL has been published until Owner release authorization. The local Python build requires a judge to download and run it. Neither proves production reliability or edge hardware operation. See `JUDGE_TESTING_GUIDE.md` and the R40 readiness report for official-rule gaps. MIT license.
