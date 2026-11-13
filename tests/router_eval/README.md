# Hybrid router acceptance corpus

`cases.jsonl` contains 150 authored synthetic semantic cases: 40 direct,
25 contextual, 20 compound, 25 indirect, 20 free-conversation, 20 unavailable.
Expected routes, timer deltas and forbidden actions are checked by
`tests/test_hybrid_eval.py` against the real dispatcher/executor/SQLite and a
fixture weather transport. These are not household transcripts or independent
holdout examples. No statistical generalization or acoustic accuracy is claimed.

Run with project Python: `python -m pytest -q tests/test_hybrid_eval.py`.
Additional privacy/concurrency/media regressions are in `test_hybrid_api.py` and
`test_hybrid.py`, outside these 150 examples. Paid boundaries are denied there.

Real-browser acceptance is a separately invoked finite harness:
`python tests/night_browser.py`. It uses production JavaScript/API on an isolated
fixture host, a real AudioContext, explicit synthetic test signals, and denies
paid provider calls. `tests/night_private_browser.py` separately checks actual
private HTTPS, clock and existing cached clips; it does not start native sessions.

Review was self-review only. No authorized independent Gemini/holdout was run.
See the filled Night Train morning report for exact suite counts and limits.
