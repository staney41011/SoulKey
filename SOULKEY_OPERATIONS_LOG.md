# SoulKey｜系統操作日誌與第 259 期交付追蹤

## 2026-10-30｜第259期「有 MP3、沒有逐字稿」根因及修正

**使用者發現**：第2堂 `05・檔案總覽` 中，有英文／泰文／西班牙文／印尼文正式 MP3，卻只有中文及英文 CC 兩份原始文稿。

**實際查核**：
- 第259期四堂 `02_翻譯稿` Drive 資料夾均空，屬實，並非只被前端隱藏。
- 中央 Sheet `英文定稿索引 + 英文定稿備存 + 多語翻譯結果 + 翻譯QA紀錄` 中已有來源受驗證的英文定稿與 10 個 AI QA 通過語言。既有 `central_tts_recovery.py` 直接讀中央表生成音檔，不會將來源寫成 Drive 正式 `.txt/.srt/.json`；而 `cloud-bridge/drive-overview.js` 只顯示 Drive 真實 `.txt`，因此會「有 MP3、沒有逐字稿」。
- AI QA 10/60：L01 `th,es`；L02 `th,es,id,vi,hi,ta,ja,ko`；L03/L04 暫無 QA pass。四堂人工英文定稿另驗證。**其餘語言不能憑空生成**，Gemini HTTP 429 尚待恢復。
- 14:04（Asia/Taipei）中央 TTS 表：L01 英、泰、西已 `done`；L02 英、泰、西、印尼、越、日已 `done`，印地語與泰米爾文為 `needs_review`（試聽音檔、未列正式交付）；韓文正在跑。以上時間為歷史快照，後續以最新 Drive 為準。

**程式修復**：[PR #26](https://github.com/staney41011/SoulKey/pull/26)，合併主程式。新增 `translation-system/central_manuscript_export.py`，依現行的英文定稿版本及完整翻譯QA核對，對每個已驗證語言匯出人可閱讀 `.txt`、`.srt`、`.json`，上傳課堂 `02_翻譯稿`，逐檔讀回核驗；如果 Drive 既有文件內容不符，**不覆寫**。正式 TTS 救援流程新增「配音前先同步文稿」，`central_tts_recovery.py --period 259 --export-only` 可做純文稿補同步，不需要再產生 MP3。專用 regression tests 和 GitHub Studio CI 通過。

**重要部署界線**：原 12:18 啟動的 Kaggle Web Job #41002147166 在修復 PR 前已 clone 程式，**不會自行更新成 #26 的新版程式**。PR 合併成功不等於 TXT 已上傳；目前四個 `02_翻譯稿` 仍需新的已授權 Kaggle 執行才能實際回填。避免 TTS 進行中重複派工或覆蓋。使用者不需要重做已完成的翻譯或重新 Google 授權。

**自動補交付設定**：[PR #27](https://github.com/staney41011/SoulKey/pull/27) 新增 `.github/workflows/p259_manuscript_backfill_after_tts.yml`，只監測 12:18 的 `Kaggle Web Job #41002147166` 第一次完成事件，然後透過 GitHub Actions API 只重跑原 `launch` job 一次。原 job 的授權輸入由 GitHub 保留，Kaggle 引導程式會 clone 新版 main（包含 #26 的中央文稿匯出），已驗證的 MP3 會重用而不重算。此自動化設有 `run_attempt == 1` 限制，避免循環觸發。**已設定 ≠ 已執行**；必須檢查後續 Workflow 是否啟動、原 runtime nonce 是否仍有效、Drive `02_翻譯稿` 是否真的出現 TXT/JSON/SRT。若原 nonce 超過 8 小時，可能無法自動成功，須以錯誤日誌判斷，不可宣稱成功。

**待辦 / 驗收**：
1. 先等 #41002147166 結束或確認中斷，核對正式 `tts:<lang>` 和 Drive MP3/preview 分別有幾組。
2. 透過**原已授權 Kaggle Bridge**執行新版文稿同步（純文稿 `--export-only` 或新版同一 rescue stage，已完成 MP3 會重用、不重算）。不得用缺憑證的新 Kaggle Notebook 取代。
3. 逐堂驗證 `02_翻譯稿` 對每個合格語言都有 TXT/SRT/JSON，且在 Studio `05・檔案總覽` 看得到 TXT。人工英文定稿和 AI QA 不可混淆。
4. 剩下未通過 QA 的語言須先排除 Gemini 429、完成翻譯 + QA，才可以送 TTS；不偽造文字/音檔。最終交付仍為 64 組文稿 + 64 組音檔。

---


## 最新驗收更新｜2026-10-30 13:27（Asia/Taipei）

> **本節比下方 12:21 的原始快照更新。** 完成數量是此時點的確認數字，正在持續運算，切勿用此數字假裝最終交付。

- [Kaggle Web Job #41002147166](https://github.com/staney41011/SoulKey/actions/runs/41002147166) 仍為 **in_progress**，GitHub `Run Kaggle job with GPU retry` 執行中。不得重複按配音派工。
- **Google Drive `04_音檔` 現有 6 組正式非空 MP3 + WAV + TTS 清單 + 對齊報告**（L01 3 組、L02 3 組、L03/L04 尚未有），中央狀態均有 `tts:<lang> done` 與「正式 MP3/WAV 與 manifest 已上傳 Drive 並校驗」。
  - **P259-L01**：`en` 12:46:45 完成；`th` 12:52:44 完成；`es` 12:55:46 完成。
  - **P259-L02**：`en` 13:17:10 完成；`th` 13:24:14 完成；`es` 13:27:24 完成。
  - **P259-L02 `id`** 於 13:27:29 開始，快照時仍為 `running`，尚不計完成。
- 實際抽驗 **P259-L02 `es` manifest**：`engine=edge-natural-v2`、`status=done`、來源 `en_backup_revision=d89bd0ee...`、`source_segment_count=53`、MP3 `27,374,253` bytes、WAV `82,119,212` bytes，包含 MP3/WAV MD5 receipts。這是檔案驗收而非單靠 GitHub 綠燈。
- **總交付仍僅 6 / 64 組已驗證音檔**，尚餘 58 組；其他語言還需依各堂翻譯與 QA 條件完成（先前 AI QA 10 / 60、4 組英文人工定稿），Gemini HTTP 429 可能阻礙後續翻譯。不能承諾其餘 58 組在本次工作完成。
- 後續更新請繼續往本頁頂端追加新的日期時間小節，不要覆寫本節，也不要在原始快照默默改數字。對照中央 Sheet `執行狀態` 與 Drive 正式檔案。

---

> **正式接手入口 / 目前狀態快照**。本文件補上 2026-10-30 救援操作的連續紀錄，避免依賴 ChatGPT 對話或個人記憶。
>
> **快照依據**：2026-10-30 台灣時間 12:21 以後，查核 GitHub Actions、中央 Google Sheet、四堂課的 Drive `04_音檔`。文件是**有時間點的人工查核紀錄**，不是會自行更新的即時儀表板。後續以最新工作日誌和 Drive 讀回結果為準。

## 0. 下一位接手者先讀

1. **正在救援**：第 259 期 P259-L01～P259-L04，4 堂 × 16 語 = **64 份目標語言文稿 + 64 組目標配音**。16 語：`en, th, es, id, vi, hi, ta, ja, ko, km, bn, ne, lo, my, it, pt`。
2. **嚴禁把 GitHub 派工成功當作 Kaggle 或音檔交付**。分層判斷：Studio POST → Apps Script 驗證 → GitHub Workflow Dispatch → Kaggle Worker 執行 → 該語完整翻譯 QA / TTS → Google Drive 非空檔案及 manifest readback → Sheet status。
3. **目前正在進行的真實工作**：[Kaggle Web Job #41002147166](https://github.com/staney41011/SoulKey/actions/runs/41002147166)，2026-10-30 12:18:20（Asia/Taipei）由 Studio 在 iPhone 上成功觸發。上次查詢時 GitHub `launch` job **in_progress**，步驟 `Run Kaggle job with GPU retry` **in_progress**。尚未證明 Kaggle 已完成。
4. **中央新紀錄**：`執行狀態` 表有 `P259-L01 / tts / queued / 41002147166 / 12:18:20`；後續有 `P259-L01 / tts / running / 12:20:36` 與 `P259-L01 / tts:en / running / 12:21:02`。這是**已開始處理的證據，尚非完成**。
5. **交付仍未完成**：截至本次查核，四堂課的正式 Drive `04_音檔` 資料夾均無可驗證輸出（0/64）。中央 `翻譯QA紀錄` 確認 AI 語言通過 **10/60**（L01：`th,es`；L02：`th,es,id,vi,hi,ta,ja,ko`；L03/L04：0）。4 組人工英文定稿另依 `英文定稿索引` / `英文定稿備存` 驗證，不能混入 AI QA 分母。
6. **主要阻礙**：獨立的 GitHub 翻譯佇列 P259-L01/L03/L04 於 2026-10-30 約 11:54～11:57（台灣時間）均碰到 Gemini HTTP 429。現有 QA 成果不得刪除、覆蓋或因 429 標記全部完成。
7. **安全**：不重設使用者 Google OAuth、原六碼 Bridge Key、Apps Script Script Properties、Drive 既有檔案；不要把 token、金鑰放入此文件、PR、前端或 Sheet。不要未確認工作狀態就再次派送相同救援。

## 1. 現行系統架構（2026-10-30）

```text
瀏覽器（iPhone / Android / 桌面）→ SoulKey Studio（GitHub Pages /studio/）
                  ├─ 課程列表、六碼驗證、狀態查詢 → 已部署的 Cloud Run 控制中心（讀取路徑）
                  └─ 正式 multi / tts 派工 → 原 Apps Script Studio Bridge（驗證 + 短效 runtime nonce）
                                              → GitHub Actions: Kaggle Web Job
                                              → Kaggle kernel: cwlmrcsir/soulkey-gpu-worker
                                              → 舊 translation-system Worker / 中央 Sheet / Google Drive
獨立現存路線：SoulKey Translation Queue Worker（GitHub CPU）；這不是上述 Kaggle TTS。
```

- 網頁入口：[SoulKey Studio](https://staney41011.github.io/SoulKey/studio/)
- 正式 Kaggle 工作流程：[.github/workflows/kaggle_web_job.yml](.github/workflows/kaggle_web_job.yml)
- 原 Apps Script 原始碼：[bridge/apps-script/Code.gs](bridge/apps-script/Code.gs)；**GitHub 更新不會自動部署到已存在的 Apps Script Web App**。
- 網頁路由：[studio/config.js](studio/config.js) 和 [studio/app-20260923-48.js](studio/app-20260923-48.js)。
- 中央 TTS 來源/執行：[translation-system/central_tts_source.py](translation-system/central_tts_source.py) / [translation-system/central_tts_recovery.py](translation-system/central_tts_recovery.py)。
- 中央 Sheet：[全球翻譯控制中心](https://docs.google.com/spreadsheets/d/1AwPqTqZSzW7Q-gLW4J5d-28dQZwVksyDnvsxNRF2uu8/edit)（重點分頁：`執行狀態`、`語言任務設定`、`翻譯工作佇列`、`翻譯QA紀錄`、`英文定稿索引`、`英文定稿備存`）。
- **舊架構不等於完整功能已恢復**。目前 iPhone 的「在 Google 獨立分頁用 POST 派工」是暫時繞過 iframe 問題的方式；不應把它當最終跨裝置 UX，也不應在此輪產出時貿然撤除。
- GitHub Actions scheduled 翻譯 Queue Worker 與 Kaggle 版 multi/tts 並存。交付狀態必須比對中央 Sheet 和 Drive，避免重覆派工或互蓋。

## 2. 2026-10-30 修復紀錄（台灣時間；PR 為永久證據）

| GitHub PR | 當次修改 | 結果／注意事項 |
|---|---|---|
| [#14](https://github.com/staney41011/SoulKey/pull/14) | 緊急 Kaggle Natural TTS launcher | 已合併；原路線偏向已過 QA 語言，不等於64組全完成 |
| [#15](https://github.com/staney41011/SoulKey/pull/15) | 恢復舊 Kaggle Web Job 路由 | 已合併；不應再把該 workflow 自動改走 GitHub CPU |
| [#16](https://github.com/staney41011/SoulKey/pull/16) | 修 Apps Script / Kaggle 網頁接線、QA來源 TTS、四堂課救援入口 | 已合併；另在中央 Sheet 啟用 P259 四堂 64/64 文稿與音檔設定 |
| [#17](https://github.com/staney41011/SoulKey/pull/17) | 修正過期 CI 規格 | 已合併 |
| [#18](https://github.com/staney41011/SoulKey/pull/18) | 四堂補譯、中央英文定稿同步、第二個救援按鈕 | 已合併；Gemini 429 是外部障礙 |
| [#19](https://github.com/staney41011/SoulKey/pull/19) | 修手機登入卡「同步中」：控制中心讀取與 Kaggle 派工分開 | 已合併 |
| [#20](https://github.com/staney41011/SoulKey/pull/20) | 修救援按鈕誤要求整站都使用 Apps Script | 已合併 |
| [#21](https://github.com/staney41011/SoulKey/pull/21) | 診斷 Apps Script 對 GitHub 無憑證訪問結果 | 已合併；匿名 403 **不得推導**登入 Safari 也 403 |
| [#22](https://github.com/staney41011/SoulKey/pull/22) | 修正無 ACK 的網頁提示 | 已合併；後續 403 根因判定已被使用者實測修正 |
| [#23](https://github.com/staney41011/SoulKey/pull/23) | iPhone 頂層分頁 POST 原 Apps Script | 已合併；12:18:20 **實際出現 GitHub run #41002147166**，因此派工路徑已獲得證據，MP3 尚待驗收 |

### 已釐清的誤判（下一位不要重犯）

- 同一 Apps Script 專案可以有多個部署 URL。使用者提供之「SoulKey public web」網址與 `studio/config.js` 的舊 Bridge 一致，**不是網站指錯網址**。
- GitHub 無憑證 GET 原 Apps Script 曾得到 HTTP 403，但使用者 Safari 直接開啟同一 URL 得到 JSON `{"ok":true,"message":"bridge-ready","bridge_protocol":9,...}`。因此**不能單憑該 403 要求重新授權或重建部署**。
- iPhone Google 獨立分頁僅顯示 `SoulKey response` 不代表成功；**同時存在 GitHub workflow_dispatch #41002147166 才是派工成功的證據**。
- Studio 讀取走 Cloud Run，不等於多語翻譯 / 音檔計算也走 Cloud Run。勿混淆控制層與運算層。
- 先救已通過 QA 的配音；其餘語言須按正確英文來源 revision 補翻譯+QA，最後才可製作音檔。

## 3. 交付與驗收表（快照，非即時）

| 課程 | 目標語言 | 已通過 AI QA | 已驗證正式 MP3 | 備註 |
|---|---:|---:|---:|---|
| P259-L01 | 16 | 2 / 15 | 0 / 16 | 12:21 `tts:en` 開始執行，尚無 Drive 讀回 |
| P259-L02 | 16 | 8 / 15 | 0 / 16 | Gemini 429，既有 QA 不重做 |
| P259-L03 | 16 | 0 / 15 | 0 / 16 | Gemini 429 |
| P259-L04 | 16 | 0 / 15 | 0 / 16 | Gemini 429 |
| **合計** | **64** | **10 / 60** | **0 / 64** | 另有 4 組人工英文定稿需按其來源確認 |

**交付完成定義**：每一 `task_id + lang` 必須有符合來源版本的正式文稿/翻譯 QA（英文用人工定稿）、非空 MP3、必要時 WAV、manifest 與 Google Drive metadata/readback。中央狀態 `done` 或合適的 `needs_review` 應有可核對證據；不能因 Actions 工作綠燈、`running` 或 `SoulKey response` 就算已交付。

## 4. 當前優先工作與禁止事項

1. **先追** [run #41002147166](https://github.com/staney41011/SoulKey/actions/runs/41002147166) 的 Kaggle kernel 狀態與實際 log：是否 `COMPLETE`、Google 授權可用、哪個語言產出 MP3，並回到 Drive / Sheet 逐項核對。**避免於此 job 執行中重複派工**。
2. 若遇到 Drive OAuth 或來源缺失，記錄確切 error、影響語言、原始 run 與已保存成果；不要推測 OAuth 全部失效或向使用者索取密碼。
3. Gemini 429：使用有上限的冷卻及續傳；保留 QA 與 source revision，禁止密集無限重試、重新產生已通過 QA 的翻譯。
4. **恢復跨裝置一致操作**須另設安全的伺服器端派工/ACK，顯示真實 GitHub run ID，經實測後才能移除 iPhone 頂層分頁臨時方案。不得直接拔掉目前唯一已被證實可送達的路線。
5. 使用者無需重新部署 Apps Script、重建六碼或再次授權，除非最新日誌已明確證明必須，且已有可復用舊設定的修復方案。

## 5. 文件維護規則（不再只靠對話記憶）

- **每次修程式的 PR**：同 PR 更新此文件的「修復紀錄／目前風險／驗收結果」；列明 PR、commit、使用者可見影響、回退方法與測試。不能只回報「修好了」。
- **每次正式工作**：記 `run_id`、啟動方式、開始／結束、工作模式、成功/失敗、Drive 輸出及讀回連結；即時資料以 GitHub Actions + Sheet + Drive 為準。本 MD **需要人或未來正式自動化程序更新**，不會因監測排程自動改寫。
- **每次接手**：先看本文件，接著核對最新 GitHub run / Sheet / Drive，不能直接拿本文件的歷史數字宣稱「現在」。
- **現存歷史文件**：[`cloud-bridge/RECOVERY_2026-10-30.md`](cloud-bridge/RECOVERY_2026-10-30.md) 是早期狀態快照；[`cloud-bridge/RELEASE_AUDIT_2026-10-29.md`](cloud-bridge/RELEASE_AUDIT_2026-10-29.md) 是遷移缺失稽核；[`translation-system/WORKFLOW_REQUIREMENTS.md`](translation-system/WORKFLOW_REQUIREMENTS.md) 是規格。三者不能取代本頁的 259 期最新操作日誌。
- **隱私／安全**：不記錄六碼 Bridge Key、GitHub PAT、OAuth refresh token、Cookie、私人授權連結或任何完整秘密。只記錄可供授權人員查核的程式與 run/工作表參照。
