# SoulKey Firebase Backup Control Center

Live: https://soulkey-control-2026.web.app/

Stage 1 is a **read-only, encrypted task snapshot** for mobile fallback when Apps Script is blocked. No mutations to original Google Sheet, Drive, Kaggle, or completed translations.

The encryption secret and plaintext task source stay on the authorized workstation and are **not committed**. `encrypt-snapshot.cjs` uses PBKDF2-SHA256 + AES-256-GCM, with fresh salt and IV per snapshot. Refresh manually with approved Sheet export, then run `node encrypt-snapshot.cjs` followed by `firebase deploy --only hosting --project soulkey-control-2026`.

Next stage: authenticated Realtime Database, live status sync, scoped write operations, per-sentence revision control, then gradual migration of Apps Script dependent actions. Do not mistake this encrypted snapshot for live Firebase database access.

## 2026-10-30：保留原 Apps Script + Firebase 增量同步

系統正式架構是 **SoulKey Studio → 原 Apps Script Web App → GitHub Actions/Kaggle → Google Sheets/Drive**；Firebase 僅作第二層控制中心及狀態鏡像，**不使用 Cloud Run/GCP 作為新的必要依賴**。

目前 Hosting 的 `data.enc.json` 仍是加密**唯讀快照**。RTDB 規則採保守預設（匿名不可讀寫、Web client 不可寫）；尚未部署新規則、同步 App Script 或確認資料庫 ID 前，不得把 Firebase 顯示為即時同步。

已在 `bridge/apps-script/Code.gs` 的 `appendExecutionStatus_` 加入 **預設停用** 的 `firebaseStatusMirror_`，原本 Sheets append 完成後才以 best-effort 寫入 Firebase；任何 Firebase 網路、權限或配額錯誤不影響原 Google Sheet/Drive。只會同步 task_id、stage、status、progress、run_id、source/output revision、時間戳，不同步逐字稿、OAuth、cookie 或音檔。

管理員確認既有 Firebase 專案建立 RTDB 與安全規則、Apps Script 執行身分具 Firebase RTDB 寫入權限且重新部署既有 Apps Script 版本後，才在該 Script Properties（不放進 GitHub）加入：

- `FIREBASE_STATUS_MIRROR_ENABLED = true`
- `FIREBASE_DATABASE_URL = https://<existing-database>.firebasedatabase.app`（填真正的 Firebase Database URL，不可猜）

原 `bridge/apps-script/appsscript.json` 的 Drive/Sheets scope 保留，另準備 `firebase.database` 及 `userinfo.email`。首次啟用新 scopes 可能需要**原持有人重新授權 Apps Script**，不得宣稱單靠 GitHub commit 就已部署。確認 Firebase RTDB 規則之後再測試單一 P259 任務狀態，並逐一核對 Sheet/RTDB 更新時間。

本身不會讓非英文缺漏自動完成；翻譯、QA、正式 Drive 字幕及 TTS 仍由原 Kaggle Web Job 處理。新 Studio `studio/config.js` 主 Bridge 已改回原 Apps Script，Firebase Hosting 位址作為補充入口。對應 CI：[Studio Status and TTS Share Tests](https://github.com/staney41011/SoulKey/actions/workflows/studio_status_batch_test.yml)，包括新增 `bridge/apps-script/tests/firebase-status-mirror.test.cjs`。
