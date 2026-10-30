# SoulKey｜系統操作日誌與第 259 期交付追蹤

## 2026-10-30 15:26（台灣）｜第259期四堂 64 文稿／64 配音續跑：實際驗收、GitHub 自動授權派工

> 這是實際執行記錄，**不是已完成 64/64 的宣告**。以 Google Drive 上正式檔案及來源 SHA/QA/manifest 讀回為最終標準。

- 真實交付快照（Drive 逐堂資料夾列舉）：L01 `3` 份已驗證文稿／`3` 組正式 MP3；L02 `9`／`7`；L03 `1`／`1`；L04 `1`／`0`，合計 **14/64 文稿、11/64 正式 MP3**。另有 L02 Hindi、Tamil 和 L04 English 三組 `needs_review` 試聽 MP3，不納入正式數。
- 中央 `翻譯QA紀錄`：非英語 **10/60** 通過；L01 `th,es`，L02 `th,es,id,vi,hi,ta,ja,ko`。L03/L04 0。全部四堂 `英文定稿索引` 各有已驗證的獨立 revision；保留既有成果，不清空 Sheet。
- 舊版原始 Kaggle Web Job [#41002147166](https://github.com/staney41011/SoulKey/actions/runs/41002147166) 已完成；一次性 backfill run [#41016642669](https://github.com/staney41011/SoulKey/actions/runs/41016642669) 的原 rerun 結果 `exported_manuscripts 14, manuscript_export_errors 0`，**不是 64 語驗收**。
- GitHub `cloud-bridge/translation_worker.py` 現在只有第259期可用 `SOULKEY_P259_GEMINI_MODEL=gemini-3.1-flash-lite`，其他期仍保留原模型；不降低 QA、鎖定英文來源 revision、完整 segment ID 審核。
- 中央 `翻譯工作佇列` 的原有四筆安全恢復為 `queued`（第10–13列）。另外新增 P259-L03、L04 的 `hi,ta,ja,ko,bn,ne,lo,my,it,pt` 十語補譯各一筆（第14–15列）。總計六筆中央工作；前面已通過 QA 的語言仍按來源 revision 複用，不重新刪改。
- [push run #41019698354](https://github.com/staney41011/SoulKey/actions/runs/41019698354) 曾因 Cloud Run OIDC 僅授權 `schedule/workflow_dispatch` 而 401；**沒有放寬 Cloud Run 身分驗證**。已移除直接 push 翻譯，建立 [one-shot kickstart #41020031810](https://github.com/staney41011/SoulKey/actions/runs/41020031810) 用 Actions 官方權限派出合法 `workflow_dispatch`，[正式翻譯 run #41020040604](https://github.com/staney41011/SoulKey/actions/runs/41020040604) 已進入 `in_progress` 的翻譯步驟（截至紀錄時）。
- 正式翻譯完成需驗證 `翻譯QA紀錄` 真正增加與 Drive TXT/SRT/JSON，之後再用已授權的 Kaggle CPU Natural TTS 校驗 MP3/WAV/manifest；該步驟此時**尚未交付新成果**。
- 遠端 Desktop Commander 月額度已達上限（連線仍在），本輪沒有嘗試重連或重置 OAuth。切勿重派相同來源造成互蓋或稱宣傳 run 成功等於 64 音檔完成。

### 15:33 QA 再次核對

- 中央 `翻譯QA紀錄` 共有 **13 個非英文 passed**：在原 10 語之外，第2堂新增 `km`、`bn`、`ne`。這 3 語尚未在 Drive `02_翻譯稿` 發現正式 TXT，也沒有新的正式 MP3；須等 Kaggle 核實上傳後才能累計成果。
- [翻譯 worker #41020040604](https://github.com/staney41011/SoulKey/actions/runs/41020040604) 仍在執行，對應 P259-L02 `running`，其餘五筆 `queued`。
- [Kaggle TTS 工作 #41020375986](https://github.com/staney41011/SoulKey/actions/runs/41020375986) 顯示 GitHub `success`，但 GitHub 紀錄僅證實 `KernelWorkerStatus.QUEUED`；無 Kaggle 實際結果或 Drive 新 MP3 的證明，因此**不增加正式配音計數**。

### 15:30 實際執行續報

- [GitHub 正式翻譯 run #41020040604](https://github.com/staney41011/SoulKey/actions/runs/41020040604) 成功由原本禁止的 push 改由合法 workflow_dispatch 啟動，Sheet 第2堂翻譯工作已顯示 `running`。
- 第2堂 **柬埔寨文 km 新增 `翻譯QA紀錄 status=passed`**，合計非英語 AI QA 從 **10/60 → 11/60**；此時仍未完成 Drive TXT / MP3 讀回驗收。
- 另已派送 [P259 Kaggle Natural TTS run #41020375986](https://github.com/staney41011/SoulKey/actions/runs/41020375986)，Kaggle API 提交 `Kernel version 2 successfully pushed`，當下讀到 `KernelWorkerStatus.QUEUED`。**GitHub job 成功僅指 kernel 已提交，不代表配音輸出成功**。請查 Kaggle `COMPLETE` 和 `TTS_DRIVE_VERIFIED` 後再計算新增 MP3；缺來源或 OAuth 失敗不能變成虛假的 done。
- 音檔入口：[Kaggle SoulKey P259 Natural TTS](https://www.kaggle.com/code/cwlmrcsir/soulkey-p259-natural-tts-emergency)。保留原 Google OAuth/Sheet/Drive 檔案；勿因救援啟動而重複派相同批次。

---


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


## 2026-10-30 17:08（台灣）｜第259期由 Gemini 切換 Kaggle Gemma 4

- 使用者要求直接切換，不再等待 Gemini API 限流。已新增 [Gemma4 翻譯／本地語意 QA 與分語言 Drive 寫回](translation-system/p259_gemma4_kaggle.py)，來源限定 P259 四堂人工英文 Final、保留 SHA 來源核對與已通過的舊 QA。模型預設官方 Kaggle `google/gemma-4/transformers/gemma-4-12b-it`、4-bit GPU；此模式不發出 Gemini API 呼叫。
- [GitHub Gemma4 Kaggle 派工流程](.github/workflows/p259_gemma4_kaggle.yml)：首次 [#41030385258](https://github.com/staney41011/SoulKey/actions/runs/41030385258) 因 Kaggle `model_sources` 未帶版本號被拒，已修正為 `.../1`。第二次 [#41030516253](https://github.com/staney41011/SoulKey/actions/runs/41030516253) 成功推出 Kaggle Notebook v1；這僅是成功提交，不是完成翻譯。
- [Kaggle Notebook](https://www.kaggle.com/code/cwlmrcsir/soulkey-p259-gemma4-translation) **已實際執行但在 Google OAuth 前置檢查失敗**：`RuntimeError: 找不到 Secret: GOOGLE_CLIENT_ID`，翻譯未啟動、沒有任何 Gemma 4 交付成果。從 [read-only Kaggle 狀態查詢 #41031073162](https://github.com/staney41011/SoulKey/actions/runs/41031073162) 的實際 kernel log 驗證。重點：Kaggle API `kernels push` 不會附掛 Notebook UI 的 Secrets（Kaggle CLI 仍無自動指定 Secret 功能）；不要再次誤報「已在跑」。
- 中央 Sheet `翻譯工作佇列` **F13:F15** 舊 Gemini `queued` 已改為 `gemma4`（J13:J15 說明接手），未刪除紀錄、不改為假 `done`；未取得正式成果前不宣稱完成。現有 GitHub Gemini worker 對 P259 的後續舊佇列重試設有 Gemini API 禁用保護（`cloud-bridge/translation_worker.py` + `soulkey_translation_queue.yml`），其他期數未切換。
- 17:04 中央 QA 查到 P259 **24/60 非英語 passed**（L01 6、L02 13、L03 5、L04 0），主要由之前 Gemini 工作者完成；**不能歸功 Gemma**。已驗證正式 MP3 最後基線仍是 11/64，沒有 Gemma 4 新文稿／新音檔交付證據。
- **解除真正阻礙的安全下一步**：由帳戶持有人在上方 Kaggle Notebook 網頁開啟 Edit → Add-ons → Secrets，授權已存在的 `GOOGLE_CLIENT_ID`、`GOOGLE_CLIENT_SECRET`、`GOOGLE_REFRESH_TOKEN` 給該 Notebook，接著用 Kaggle 網頁 Save & Run All（**不是**再用 GitHub `kernels push`）。勿把 Secrets 內容貼入聊天、GitHub 原始碼、Kaggle 程式碼或 Logs。完成後以 Kaggle 記錄及中央 Sheet / Drive readback 實際驗收。


### 2026-10-30 17:19（台灣）｜已勾選 Kaggle Secrets，API 重送仍無法帶入

- 使用者已在 Kaggle Notebook 啟用三項 Google OAuth Secrets；不要求重新勾選。
- 已重跑 [Gemma4 派工 #41031483823 attempt 2](https://github.com/staney41011/SoulKey/actions/runs/41031483823)。GitHub 僅成功提交新 Kaggle 版本。
- [Runtime status #41031073162](https://github.com/staney41011/SoulKey/actions/runs/41031073162) 追查後，Kaggle kernel 從 RUNNING 轉成 ERROR，仍於 GOOGLE_CLIENT_ID 讀取失敗；沒有任何新增的 Gemma 文稿或音檔驗收證據。
- 根因：Kaggle CLI kernels push 不會把 Notebook 網頁已授權的 Secrets 附掛至新的 API 派工版本。已核對 Kaggle CLI 文件及官方討論，禁止把憑證字串寫入 GitHub / Notebook 原始碼。
- 唯一尚需使用者執行的操作：在 [同一個 Kaggle Notebook](https://www.kaggle.com/code/cwlmrcsir/soulkey-p259-gemma4-translation) 開啟 Edit，保留 GPU，按 Save Version → Save & Run All。**不要再由 GitHub API push**，以免再產出未附 Secrets 的版本。之後核對 Kaggle 真正 Log、中央 Sheet、Drive。


### 2026-10-30 17:42（台灣）｜正式修復第259期 Gemma4 授權接線（非交付宣告）

- **已修正根因**：第259期原本獨立 Kaggle Gemma Notebook 透過 CLI push 無法取得 Kaggle Secrets，正式路徑已改為 Studio 既有 `run_stage(task_id=P259-L01,stage=multi,lang=central4)` → 原 Apps Script Bridge 產生 8 小時 runtime nonce → `kaggle_web_job.yml` → `web_job_worker.py` 取得短效 `GOOGLE_ACCESS_TOKEN`、`SOULKEY_BRIDGE_URL`、`SOULKEY_RUNTIME_NONCE` → GPU `p259_gemma4_kaggle.py` → 中央 Sheet/Drive 正式文稿 → `central_tts_recovery.py` Edge TTS。**不再要求 Kaggle Notebook 的 Google Secrets，翻譯與本地 QA 不呼叫 Gemini API**。
- `translation-system/web_job_worker.py` P259 的 `multi`（含 `central4`）改走 Gemma 4；原 Gemini central4 分支已移除；其他期數未變。補正 GPU preflight 不再為 Gemma4 強制要求 CTranslate2。
- `.github/workflows/kaggle_web_job.yml` 只有 P259 multi 改用 T4 GPU、掛載 Kaggle 官方 `google/gemma-4/transformers/gemma-4-12b-it/1`、4h 工作時間；原 Apps Script workflow_dispatch/nonce 機制保持不變。
- `translation-system/p259_gemma4_kaggle.py` 固定上述模型版本並採用 Gemma4 官方 Transformers processor chat template。保留已通過 QA 的來源 SHA，失敗語言隔離，語言獨立寫回；只對通過 QA 的來源進行 Edge TTS。
- `studio/app-20260923-48.js` 第259期四堂補譯救援按鈕確認文字更新為 Gemma4，原使用者操作入口不更動，無須重部署 Apps Script。
- **測試**：[GitHub P259 Gemma4 Bridge Integration Check #41035224870](https://github.com/staney41011/SoulKey/actions/runs/41035224870) 已成功（`py_compile`、純函數 self-test、Bridge OAuth 接線、GPU/模型版本一致性）。這是靜態／離線整合測試，**不是 Kaggle GPU 實際模型載入與翻譯交付驗收**。
- **下一個必需動作**：由已登入 Studio 的使用者按一次「第259期四堂課補譯」啟動原 Apps Script Bridge 的新 runtime nonce，GitHub 才能取得有效短效 Google Token；不可重用舊 nonce、不可從 log 挖取憑證、不可再用獨立 `p259_gemma4_kaggle.yml` 的失敗型直接派工。確認 GitHub Kaggle Web Job 的新 run ID、Kaggle 真正 log，以及中央 Sheet `翻譯QA紀錄` 和 Drive 的新增 TXT/SRT/JSON/正式 MP3 才能宣告交付。
