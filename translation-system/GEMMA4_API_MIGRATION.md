# SoulKey translation: Gemma 4 API migration (2026-11-01)

## Runtime architecture

- **Website:** existing GitHub Pages Studio; no frontend or login protocol change.
- **Coordination:** existing Apps Script Bridge, Google Sheets and Google Drive; no Google Cloud Platform (GCP), Vertex AI, service account, or VM required for hosted Gemma 4 text calls.
- **CPU translation worker:** existing `translation-system/web_job_worker.py` invokes `gemini_text_production_runner.py` (Chinese polish, vernacular, English) and `gemini_multi_production_runner.py` (15 target languages, QA, repair).
- **Text model:** `gemma-4-26b-a4b-it` via Google AI Studio Gemini API **`/v1beta/models/{model}:generateContent`**, *not* the Gemini Interactions `/v1beta/interactions` endpoint.
- **Override:** `SOULKEY_TEXT_MODEL` / `SOULKEY_REPAIR_MODEL`; do not set these to unsupported model identifiers. Keep Gemma 4 for all text-stage tasks.
- **API key:** existing Apps Script `GEMINI_API_KEY` Script Property, passed to the worker over the already-existing short-lived runtime access flow. This variable name is historical; it works for Gemma 4 hosted by Google AI Studio. Never embed it into Git, HTML, browser JS, or log output.
- **ASR:** existing verified Taiwan-Breeze/Kaggle input and source revision flow. An existing Gemini-video fallback is still a separate legacy video source operation and is **not** an instance of Gemma 4 text translation.
- **Audio:** existing Natural TTS v2 / Edge TTS, not Gemma 4. Gemma 4 26B returns text, not a speech audio track.

## Data invariants

1. Do not regenerate user-approved Chinese/English Final or previously approved target-language documents just to switch models.
2. Retain segment IDs, timestamps, glossary, source SHA-256, Drive canonical filenames, and the resumable multi-translation checkpoint v4 schema.
3. Migrate only missing or stale-language segments that the current plan requests, preserving all previously completed translations.
4. JSON response contract: prefer `responseMimeType=application/json` and `responseSchema`; if a hosting configuration explicitly rejects the schema, retry with JSON mode plus full schema in the prompt. Reject empty/invalid JSON; keep existing downstream ID and target-language QA.
5. A model-generated AI QA pass is **not** human approval. Do not mark unreviewed P259 manuscripts or MP3s as formally delivered.

## Verification and rollout

- Offline: `cd translation-system && python -m unittest -v tests/test_gemini_engine.py tests/test_gemma4_api.py`; the normal SoulKey MVP Validate workflow also runs this.
- Online, non-writing: `.github/workflows/gemma4_api_live_smoke.yml` runs a tiny 1-segment translation with `secrets.GEMINI_API_KEY` on the isolated migration branch, if that secret exists. It makes **no** Google Drive or Sheets modifications.
- Publish to `main` only after offline tests and the live probe pass; copy only the migration-related files, not the separate P259 recovery workflows from the delivery branch.
- Apps Script redeployment is **not required** for this Python-only model routing change, as the existing Bridge already supplies `gemini_api_key`. Existing translation job dispatch must continue to start workers from the current `main` branch.
- Rollback: restore prior text model and prior `gemini_engine.py` implementation from the pre-change commit on `main`; leave Drive data and checkpoint files intact.

## Caveats

Gemma 4 free-tier usage is rate-limited by Google AI Studio. HTTP 429 and transient server failures are retried with the existing worker backoff; the multi runner persists checkpoints so later resumes do not rewrite completed language batches. Source-video understanding and audio synthesis are intentionally separate and **not** replaced by a text-only model.
