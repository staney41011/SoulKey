# SoulKey repository operating rules

## Google Apps Script deployment is part of every Bridge change

The owner explicitly requires: **Never stop at a GitHub commit when changing Apps Script. Deploy the production Apps Script yourself and verify it, without asking the owner to remind you.**

### Production targets
- Apps Script project ID: `1bHp7jaEZJgFQ_4D-TKa4xMbtYqVbImHykojtMF-NCnr4n6Ey9srF-MhM`
- Production Web App deployment ID: `AKfycbyyMjEUqDdhsXWwCWKRTjpyhzdrdXnKhJYZIyiQ-QblOR_nhUdxtv9tqujw5VHkbyZ3`
- Public health endpoint: `https://script.google.com/macros/s/AKfycbyyMjEUqDdhsXWwCWKRTjpyhzdrdXnKhJYZIyiQ-QblOR_nhUdxtv9tqujw5VHkbyZ3/exec?action=bridge_preflight`
- Apps Script source of truth: `bridge/apps-script/*.gs` and `bridge/apps-script/appsscript.json`.
- Keep the original deployment ID (and therefore the public /exec URL) intact. Avoid deploying a new URL or updating any other deployment unless specifically required.

### Mandatory sequence for every future Apps Script source edit
1. Check the latest GitHub branch and the current remote Apps Script source. Back up the remote source with authenticated `clasp pull` into a distinct temporary directory; do not overwrite unsaved remote changes.
2. Run JavaScript syntax and relevant native/studio tests before changing production. If validation fails, fix first.
3. Use an authorized `clasp` session to push the exact updated source files (all six `Code.gs` / `Native*.gs` files and the manifest) into the existing Apps Script project. Never place OAuth credentials in the repo or frontend.
4. **Update the existing formal Web App deployment**, e.g. `clasp deploy --deploymentId AKfycbyyMjEUqDdhsXWwCWKRTjpyhzdrdXnKhJYZIyiQ-QblOR_nhUdxtv9tqujw5VHkbyZ3 --description "SoulKey GitHub <sha>"`.
5. Read back `clasp deployments` and verify the formal deployment version incremented. Perform a real request to `action=bridge_preflight` and require HTTP 200 and `"bridge-ready"`. Check relevant runtime behavior where possible.
6. Report both the GitHub commit and the newly deployed Apps Script version. **A successful GitHub Actions run is not proof of an Apps Script deployment.** If authentication, network, or authorization prevents deployment, state that the source was updated but production was *not* updated; never claim success or ask the owner to perform routine manual copy/paste.

### Verified state at 2026-11-15
- Remote HEAD source matched GitHub commit `e82d21e` byte-for-byte after newline normalization.
- Formal deployment was updated from v107 to **v108** using `clasp deploy --deploymentId` (without changing its URL).
- Public `bridge_preflight` returned HTTP 200 and `{"ok":true,"message":"bridge-ready",...}`.
- A remote-source snapshot was taken first.
- This policy file only changes documentation, not Apps Script runtime source, so it does not itself require a new Apps Script version.

## Other protections
- Do not change root `index.html` or `.github/workflows/update_dm.yml` for Studio changes.
- Studio lives under `studio/`.
- Do not expose GitHub tokens, Google OAuth tokens, API keys, or `clasp` credentials.
