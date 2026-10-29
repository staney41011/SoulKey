#!/usr/bin/env bash
# Deploy SoulKey Cloud Bridge from an already-authorized Google Cloud Shell.
# Does not read, print, replace, or commit the existing BRIDGE_KEY/Google secrets.
set -euo pipefail

PROJECT="translate-system-509202"
REGION="asia-east1"
SERVICE="soulkey-bridge"
EXPECTED_PUBLIC_URL="https://soulkey-bridge-214901732194.asia-east1.run.app"

if [[ ! -f cloud-bridge/server.js || ! -d .git ]]; then
  echo "ERROR: Run from the root directory of the SoulKey GitHub checkout." >&2
  exit 2
fi
command -v gcloud >/dev/null || { echo "ERROR: gcloud not installed; use Google Cloud Shell." >&2; exit 2; }
command -v node >/dev/null || { echo "ERROR: Node.js is required for the preflight tests." >&2; exit 2; }
command -v python3 >/dev/null || { echo "ERROR: Python 3 is required." >&2; exit 2; }
[[ -n "$(gcloud auth list --filter='status:ACTIVE' --format='value(account)' 2>/dev/null)" ]] ||
  { echo "ERROR: Google Cloud authentication is missing." >&2; exit 2; }

echo "Checking existing Cloud Run service (will not create a replacement)..."
gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" >/dev/null ||
  { echo "ERROR: Existing service cannot be read. No deployment attempted." >&2; exit 2; }

REVISION="$(git rev-parse HEAD)"
echo "Source commit: $REVISION"
echo "Running dependency-free regression checks..."
node --check cloud-bridge/server.js
node --check cloud-bridge/translation-queue.js
node --check cloud-bridge/youtube-cc-queue.js
node cloud-bridge/tests/sheets-request.test.js
node cloud-bridge/tests/english-final-source.test.js
node cloud-bridge/tests/central-writes.test.js
node cloud-bridge/tests/github-worker-auth.test.js
node cloud-bridge/tests/translation-queue.test.js
node cloud-bridge/tests/translation-chunk.test.js
node cloud-bridge/tests/translation-resume.test.js
node cloud-bridge/tests/youtube-cc-queue.test.js
node cloud-bridge/tests/youtube-cc-progressive.test.js
python3 -m py_compile cloud-bridge/translation_worker.py cloud-bridge/youtube_cc_worker.py cloud-bridge/youtube_cc_kaggle.py
python3 -m unittest discover -s cloud-bridge/tests -p 'test_cc_english_first.py' -v
python3 -m unittest discover -s cloud-bridge/tests -p 'test_youtube_cookie_env.py' -v

echo "Deploying existing service; --update-env-vars preserves existing Bridge keys and settings..."
gcloud run deploy "$SERVICE" \
  --source cloud-bridge \
  --project "$PROJECT" \
  --region "$REGION" \
  --platform managed \
  --update-env-vars "SOULKEY_BUILD_SHA=$REVISION" \
  --quiet

SERVICE_URL="$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format='value(status.url)')"
[[ "$SERVICE_URL" == https://* ]] || { echo "ERROR: Cloud Run did not return a service URL."; exit 3; }
echo "Deployment URL: $SERVICE_URL"
if [[ "$SERVICE_URL" != "$EXPECTED_PUBLIC_URL" ]]; then
  echo "WARNING: Studio configured URL differs; check studio/config.js before using the browser."
fi

echo "Checking deployed build identity (no user secret involved)..."
RESPONSE="$(curl --fail --silent --show-error --max-time 25 "$SERVICE_URL/")"
printf '%s' "$RESPONSE" | python3 -c '
import json,sys
data=json.load(sys.stdin)
if data.get("message")!="bridge-ready":
    raise SystemExit("ERROR: wrong bridge service response")
if data.get("build")!=sys.argv[1]:
    raise SystemExit("ERROR: source and deployed build mismatch")
print("CLOUD_BRIDGE_BUILD_VERIFIED",data["build"])
' "$REVISION"
echo "Code deployment verified. Open Studio, reconnect with the existing six-digit Bridge Key,"
echo "then check status_health and confirm new queued jobs are claimed by GitHub Actions."
echo "NOTE: Deployment success does not prove Kaggle/translation/TTS execution; verify actual Sheet results."
