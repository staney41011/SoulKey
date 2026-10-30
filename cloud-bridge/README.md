# Archived control service

As of 2026-10-31, this service is retired. Production uses the original Apps Script, Google Sheets/Drive, GitHub Actions and Kaggle. Do not deploy Cloud Run or re-enable its workers. Historical code and records remain for recovery; pure translation QA utilities may still be imported locally.

# SoulKey Cloud Run Bridge — Google Sheet + GitHub Worker

Project: translate-system-509202 / asia-east1 / soulkey-bridge.

The original six-character Bridge Key remains the only user-facing login.

Read-only APIs: task list, task status, course files, review manuscripts,
English/Chinese confirmation status, language settings.
Write APIs: English sentence edits, verified English full Final, multi-language
translation queue. The translation queue persists jobs in the existing Google
Sheet, not a browser-only state. Background GitHub Actions use short-lived
repo-bound OIDC identity (no GitHub PAT, no private Google access token).

GitHub Workflow: .github/workflows/soulkey_translation_queue.yml
Offline translator: cloud-bridge/nllb_cpu.py (NLLB 600M INT8, CC-BY-NC 4.0).
When GEMINI_API_KEY is configured, the Gemini translator is preferred;
otherwise, NLLB provides a slower non-commercial draft fallback. No job
is marked done without verifying all expected translated segments in Sheet.

Google Drive audio/TTS publishing and other original Apps Script write actions
remain unavailable until separately restored. Never claim they are complete.
No Bridge Key or service credentials should be committed to GitHub.

Running code in GitHub does NOT deploy Cloud Run. Source deploy the
cloud-bridge directory in the GCP project using authorized gcloud credentials
and verify status_health.translation_queue_enabled is true.


## P259 complete delivery / source-verified Natural TTS (2026-10-30)

New dedicated delivery lane: `.github/workflows/soulkey_p259_final_delivery.yml`.

- Only the dedicated GitHub workflow on `main` may request temporary Google Drive credentials from `worker_drive_runtime`; other GitHub workflows, PRs, anonymous callers and the six-digit Bridge Key cannot call it.
- The Bridge prefers the **existing owner OAuth** when `GOOGLE_OWNER_CLIENT_ID`, `GOOGLE_OWNER_CLIENT_SECRET`, `GOOGLE_OWNER_REFRESH_TOKEN` are already configured. It otherwise uses its Cloud Run service identity. No refresh token is copied into GitHub or Kaggle.
- The authorized Google identity must have **Editor** capability on *all four lessons'* `02_翻譯稿` and `04_音檔` folders. The API refuses to return an access token before verifying those eight folder capabilities.
- GitHub Action obtains short-lived access tokens with repo-bound OIDC, refreshes them during long TTS jobs, and reuses existing `central_tts_recovery.py`: only matching human English Final and fully QA-approved translations can be published. The publisher checks JSON/TXT/SRT readback, actual MP3/WAV/manifest and MD5.
- If `P259-L04` has no `source_info.json`, the new `p259_source_duration_restore.py` independently verifies the **registered YouTube video ID** and duration before first upload; unverified source metadata remains a `needs_review` blocker, never fabricated.
- Read-only `p259_delivery_audit.py` checks all **4×16** approved sources, exact manuscript bytes and formal audio receipts, and emits an acceptance JSON. Partial success can never be claimed as 64/64.
- The scheduled delivery workflow is **intentionally gated** behind the GitHub Actions repository variable `SOULKEY_P259_DELIVERY_READY=true`. Manual workflow dispatch is available before enabling scheduled runs and gives a real permission/write test.

### One-time activation on the already-authorized Google Cloud Shell

Run this in the **existing SoulKey git checkout**, not an arbitrary directory:

```bash
git pull --ff-only && bash cloud-bridge/deploy-from-cloud-shell.sh
```

The script checks the existing Cloud Run service, runs repo tests, deploys it while preserving all existing Bridge Key and secrets, then compares the **deployed build SHA** with the source commit. It prints the Cloud Run service account email, without exposing credentials.

Next, open `https://github.com/staney41011/SoulKey/actions/workflows/soulkey_p259_final_delivery.yml` and manually dispatch `export_only=true` once. Its step `P259_DELIVERY_BRIDGE_FOUR_LESSON_DRIVE_WRITE_VERIFIED` must pass and real manuscript logs `CENTRAL_MANUSCRIPT_DRIVE_VERIFIED` must be present before proceeding. If access fails, share the eight lesson text/audio folders with the printed service account as Editor (unless the existing owner OAuth already has permission); then rerun the probe.

Finally set `SOULKEY_P259_DELIVERY_READY=true` in repository Settings → Secrets and variables → Actions → Variables to enable bounded scheduled deliveries. Do **not** enable on CI green alone.

Do not mark the task complete until the strict audit reports `64 / 64 / 64` (English Final + 60 QA, formal manuscripts, formal MP3). If a language is still QA-failed, only its independent Gemma4 translation job can clear the block. Programmatic source changes alone do not deploy Cloud Run.
