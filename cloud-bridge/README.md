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
