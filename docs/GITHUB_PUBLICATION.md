# GitHub publication audit — 10 November 2026

Owner target: https://github.com/anpavel84-afk/gobot-home . The owner changed the
requested visibility from private to **public** before any project code was pushed.
The GitHub connector and local GitHub CLI both verified the intended account.

Initial source audit through local commit `190a3fd`: 6 reachable commits, 262 unique
historical blobs, 193 historical paths. Gitleaks 8.30.1 full-history `--all` scan:
0 findings; current tracked-files snapshot: 0 findings. Output was captured with
100% secret redaction; raw reports remain in ignored run/github-audit/.
An independent path/magic audit found no auth stores, real environment files,
SQLite databases, voice recordings, certificates or private keys in the history.
Only .env.example is an allowed environment template. All actual runtime data,
model files, CLI homes, TLS and DPAPI stores remain ignored. Ignore rules were
strengthened for future accidental additions. Scanner results are evidence,
not a guarantee that no conceivable sensitive information can exist.

Scanner is project-local run/tools/gitleaks/gitleaks.exe, not a global installation.
Official release archive SHA256:
`d29144deff3a68aa93ced33dddf84b7fdc26070add4aa0f4513094c8332afc4e`.
Release: https://github.com/gitleaks/gitleaks/releases/tag/v8.30.1 .

Existing remote main contains its initial README commit and is preserved. Local
development branch is master. Publication creates origin/master without force,
reset, history rewriting or deleting main. Work in progress is not included in
the initial infrastructure commit; subsequent code changes must pass checks first.
No releases or deployment services are created; GitHub Actions are disabled.

Normal workflow: local changes → relevant pytest/Node checks → review staged diff
and secret scan → commit → git push. Credentials remain in the existing gh login;
the repository-local credential helper contains a command, not a token. Global
Git configuration, SSH files and existing CLI account stores are not changed.

Device/composer publication check: all 227 index files scanned with Gitleaks
8.30.1, 0 findings. Independent path/magic checks found 0 private artifacts.
The only binary files are the project's two procedural PWA PNG icons; no family
photographs or voice recordings are tracked. 519 pytest and five Node fixtures
passed; private HTTPS device/image checks made no paid model requests and saved
no test dialogue. Public visibility, master default and disabled Actions were
confirmed again before push. iPhone rendering/wake-word quality remain unverified;
source publication does not imply hardware or acoustic acceptance.

M1/v0.2 checkpoint: docs-only update 96e0f3d preserved the existing code tree.
242 tracked files were reviewed/scanned, including one explicitly allowed synthetic
feedback WAV. Its hash and provenance are in feedback-asset.json; it is not a
family recording. Full-history scans remained at zero findings. Code/runtime
checkpoint 17224e1 passed 528 tests and the private HTTPS mock trace smoke.
The subsequent trace report is documentation only and does not require a restart.
Paid profiling and physical iPhone latency remain unverified pending owner budget.
