# SoulKey Firebase Backup Control Center

Live: https://soulkey-control-2026.web.app/

Stage 1 is a **read-only, encrypted task snapshot** for mobile fallback when Apps Script is blocked. No mutations to original Google Sheet, Drive, Kaggle, or completed translations.

The encryption secret and plaintext task source stay on the authorized workstation and are **not committed**. `encrypt-snapshot.cjs` uses PBKDF2-SHA256 + AES-256-GCM, with fresh salt and IV per snapshot. Refresh manually with approved Sheet export, then run `node encrypt-snapshot.cjs` followed by `firebase deploy --only hosting --project soulkey-control-2026`.

Next stage: authenticated Realtime Database, live status sync, scoped write operations, per-sentence revision control, then gradual migration of Apps Script dependent actions. Do not mistake this encrypted snapshot for live Firebase database access.
