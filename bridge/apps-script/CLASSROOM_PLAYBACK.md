# SoulKey 課堂播放音檔（雙份保存）

本功能自第 261 期起，連接現行的 `soulkeyNextAudioTick`，使用相同的 15 分鐘 Apps Script 排程，不新增公開 webhook、不改既有配音流程。

- **原始工作區**：原本的 MP3、WAV、QA 報告、來源文稿、雲端音檔驗收紀錄及版本資訊均完整保留。
- **課堂播放區**：Google Drive「所有口譯檔案」資料夾 `1Z2BTD_WvMG08VSa3MSECFNj1yy_UuO66`，採 `期數/語言/第N期_第M堂課_課名_講師_語言TTS音檔.mp3`。
- 翻譯 QA 或配音驗收未通過的可播放音檔，同樣建立**額外**的 `_待驗收.mp3` 課堂副本。
- 使用 `DriveApp.File.makeCopy()` 直接在 Google Drive 伺服端複製，不下載或重新上傳大型 MP3。
- 同一個來源 ID、檔案雜湊與審核狀態重跑不建立重複副本。成功後另存 `sheets.native_playback.<語言>.json` 同步紀錄。
- 後續修正版本會將舊的**系統產生**的副本改為 `_舊版_<短雜湊>.mp3`，保留備查；手動上傳的檔案永不覆蓋或重新命名。
- **自動副本與正式驗收完全分離**：課堂播放副本同步失敗，原本 MP3/WAV 依然正常保存；下一輪排程重試。
- 網頁「多語翻譯／配音進度」同時顯示原始音檔與課堂副本的獨立連結。

核心程式：`bridge/apps-script/NativePlayback.gs`（歸檔／冪等性）、`NativeAudio.gs`（15 分鐘觸發／續跑）、`NativeStudio.gs`（唯讀副本狀態）。

測試：`node bridge/apps-script/test_classroom_playback_copy.js`、`node bridge/apps-script/test_apps_script_load_order.js`。最終需要用新一期第一個實際 MP3 核實執行帳號是否能對目標資料夾建立副本；若 Google Drive 拒絕複製，原工作區不受影響，排程會繼續嘗試。
