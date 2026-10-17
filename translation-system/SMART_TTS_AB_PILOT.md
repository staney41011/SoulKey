# SoulKey 智慧配音 A＋B：試行版

狀態：**已啟用正式配音預設流程**。Studio 配音、Studio 完成課程與批次課程都使用 A＋B 智慧配音；既有已驗收音檔不自動重製。

## 已決定的原則

1. 各語言的完整翻譯稿（JSON/TXT/SRT）保留不變。配音稿另外保存成 `<lang>.narration_script.json`。
2. 保留所有故事、事件順序、佛理、數字、人物、比喻和結論。只改冗長的說法。每項 AI 改寫需通過另一輪獨立語意審查，還要通過本機數字檢查。
3. 原影片為**絕對時長上限**，沒有最低長度目標。試行模式不做整段的強制加速或放慢。
4. 在句尾、故事／章節轉折加入約 0.12–0.55 秒的短停頓，根據原字幕時間間距決定，不填補整堂差額。
5. 初次自然配音符合時長就不額外修改。超時才啟動最多三輪修稿，每輪最多八個較長、可修改的區塊；候選區塊先 AI 審核，再單獨合成、實際測量，只有真的縮時才取代該區塊。
6. 最終編碼後的 MP3 必須由 ffprobe 再測量一次，長度不得大於原片；不得裁切結尾或藉由刪掉故事換時間。若找不到原片的可靠 source_info.json 時長，禁止標記交付完成。
7. 若未達標，只留下配音稿與審核報告，**不上傳超時的 MP3**，不改寫已合格的正式 MP3／manifest。

## 正式運作及手動啟動

```bash
python translation-system/tts_runner.py \
  --task-id P257-L01 --langs id --strict-delivery
```

Studio 啟動 TTS／完成課程，或批次工作執行 TTS，均已自動啟用智慧配音。需要 Google Drive/Sheets 存取授權、Edge TTS、FFmpeg、FFprobe；超時改寫時才需要 Gemini API。一般執行會保留同來源、同聲線的已完成正式音檔；需要重製時必須使用 --force。

## 驗收與紀錄

正式完成需同時滿足：獨立語意 QA 通過、無不可接受的音檔問題、最終 MP3 實測時間小於等於來源。記錄 `smart_fit_report.json`（各輪採納／拒絕原因、節省秒數、自然停頓、逐區塊的原片與配音時間偏移）。

主要內容錨點的偏移是**警示資料，不是強制逐句同步**。如果錨點偏差很大，要另外製作 YouTube 對時版；不宣稱整堂長度合格就等於精確同步。

## 試行限制

- 本次正式上線不代表全語言整堂音訊都已聽感驗收；這個版本用原文／候選配音稿的每一個 *TTS block* 進行局部修改。跨區塊重新安排語序或故事尚不支援；避免改亂字幕對應。
- 模型的獨立 QA 是安全網，但無法保證判斷零錯誤，重要的經典引文與佛理仍建議由各國人員抽查。
- 原本已儲存的雲端合格 MP3 不會被掃描、追溯重製；要正式測試一堂課，需在授權主機**明確指定** task ID 和語言。
- 自動修改以長區塊為優先；如果三輪都無法滿足上限，狀態必須維持 needs_review，不用硬加速、刪故事、裁切語音充數。

## 本地測試

```bash
cd translation-system
python -m unittest -v tests/test_smart_tts_fit.py
python -m unittest -v tests/test_tts_duration_fit.py
python -m unittest -v tests/test_natural_tts_punctuation_pause.py
```
