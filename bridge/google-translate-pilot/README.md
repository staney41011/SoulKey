# SoulKey 第260期｜Google Translate + Apps Script 初譯測試

這是獨立的 **Google Apps Script** 測試專案。**不替換、修改既有 Bridge、ASR、人工中英定稿、多語正式成果或配音**。

- Apps Script: https://script.google.com/d/1C6TspGdqYBqVj8vwPAGE4U9KNKnOiOMjBlnT8tae0icK-fuff6IsA0HQ/edit
- 中央控制中心: https://docs.google.com/spreadsheets/d/1AwPqTqZSzW7Q-gLW4J5d-28dQZwVksyDnvsxNRF2uu8/edit
- 測試資料表: `AppsScript初譯`
- 進度資料表: `AppsScript初譯任務`
- 本機部署程式: `C:\Users\a1001\Documents\SoulKey-GoogleTranslate-P260-Test`

## 已匯入與驗證

四份英文人工定稿文件從既有「第260期/01_課程/第X堂/02_翻譯稿」讀取。每堂分別 58、36、50、48 段，共 192 段。
2026-11-05 透過 Sheets `GOOGLETRANSLATE` 公式，在四堂各前三段產生所有15語，共 180 個非空結果，已凍結為靜態字串；這是翻譯引擎與試算表讀寫驗證，**不是 LanguageApp/完整 QA 已完成**。

## 首次啟用（需腳本擁有者一次性 Google 授權）

1. 開啟上述 Apps Script 連結，確認程式為 `SoulKey P260 Google Translate Test`。
2. 在上方函式選單選 `soulkeyP260StartFull`，按「執行」並批准 Google 試算表、雲端硬碟、觸發器權限。
3. 程式先確保四堂英文定稿與測試表同步，保留來源未變的 180 個已驗證翻譯，再建立每5分鐘執行一次的觸發器。其後自動由 `soulkeyP260Tick` 續跑未完成的語言。
4. 在「AppsScript初譯任務」檢視進度，或在 Apps Script 手動執行 `soulkeyP260Status`。
5. 如需停止，執行 `soulkeyP260Stop`；它只停測試觸發器，不刪除已翻譯內容。
6. 所有目標語完成後，可執行 `soulkeyP260ExportDrafts`，於各堂 `02_翻譯稿/AppsScript初譯-待QA` 輸出獨立草稿。這些 JSON **待 Gemma 4 語意 QA**，不得直接視為正式 TTS 譯稿。

## 安全與恢復

- 每個格子寫入即保存，不依靠大量公式持續重算。
- 以原始 `segment_id/start/end` 對齊，不合併段落；英文修改才清除該段測試初譯。
- 若權限/配額/暫時錯誤，已完成格子保持不變。每5分鐘最多120個翻譯呼叫（依執行時間提前停止），每次最長約4分鐘；翻譯計數以24小時視窗保護，每個視窗最多4200次。
- 不覆蓋正式 `多語翻譯結果` 工作表，不變更主佇列狀態；初譯與 QA 成果須另外核准後才能導入既有 TTS。
- 不需要新增 GCP 專案，也不需要付費 Cloud Translation API。
- `clasp run` 需另設 API Executable 與特殊 Google OAuth 設定。本次未走該路徑以遵守「不使用 GCP」的需求，因此首次實際 LanguageApp 執行需透過 Apps Script 編輯器授權。

## 尚未驗證

- Google Apps Script 帳號層級 `LanguageApp.translate` 在本新專案的首次授權與實際執行。
- 全部 192 段 × 15 語的完整結果。
- Gemma 4 對這批 Google 初譯的逐語意 QA、最終正式稿發佈與配音；測試期間不得宣稱已完成。

## 2026-11-05 加速版 v2

- 舊版每翻譯一格就寫一次配額與多次 Sheet 單格更新，造成大量服務往返。
- 新版每段最多15語僅做一次 `setValues()` 批次寫回，一段做一次保守的配額預留；不改動原本來源 hash、時間軸或先前完成的譯文。
- 第一次 v2 定時成功執行後，腳本自動把舊版10分鐘排程改成5分鐘；每批最多120次翻譯（實際受4分鐘上限、Google帳號配額與觸發器總執行時間限制）。
- 本機 `test_batch.js` 模擬測試通過：10個語言新譯、5個保留、1次Sheet寫入、1次配額寫入；完整的列則不重做。
- 部署與模擬測試不等於實測達到某個倍數，須看下一批觸發器的真實執行時間及新增格數。
