# SoulKey Natural TTS v2｜待上線完整流程

狀態：READY-BRANCH / 尚未上線
分支：feature/natural-tts-v2-ready

## 核心原則
1. 正式翻譯稿決定「說什麼」，TTS 只決定「怎麼說」。
2. English 以 en.final.json 為正式來源；其他語言優先 <lang>.final.json，沒有 final 時才允許既有 <lang>.json。
3. YouTube 自動配音不再默默取代 SoulKey 正式音檔，只保留為參考／比較來源。
4. 字幕切點與 TTS 合成切點分離，不再一個 CC cue 一次 TTS。
5. 新音檔先產生到 staging，QA 通過後才替換正式 canonical 檔案。
6. 任一語言失敗不得影響其他已成功語言。
7. 來源文字 revision / SHA 改變後，舊 TTS 自動標記 stale。
8. Edge Natural 走 Kaggle CPU；需要 MMS 的語言或手動 fallback 才使用 T4。

## 語言與正式引擎
| lang | 語言 | 主引擎 | voice | rate | fallback |
|---|---|---|---|---:|---|
| en | English | Edge Natural | en-US-AndrewMultilingualNeural | -4% | MMS |
| th | Thai | Edge Natural | th-TH-NiwatNeural | -3% | MMS |
| es | Spanish | Edge Natural | es-US-AlonsoNeural | -3% | MMS |
| id | Indonesian | Edge Natural | id-ID-ArdiNeural | -3% | MMS |
| vi | Vietnamese | Edge Natural | vi-VN-NamMinhNeural | -3% | MMS |
| ta | Tamil | Edge Natural | ta-IN-ValluvarNeural | -3% | MMS |
| hi | Hindi | Edge Natural | hi-IN-MadhurNeural | -3% | facebook/mms-tts-hin |

Hindi 使用原生 hi-IN Neural voice；MMS Hindi（facebook/mms-tts-hin）只保留為故障 fallback。

## 正式資料流
Final Transcript
→ Speech Text Sanitizer
→ Cross-segment exact overlap cleanup
→ Semantic Speech Block Builder
→ TTS Engine Router
→ Per-block synthesis
→ Audio integrity QA
→ Natural Preview assembly
→ Timeline Dub assembly
→ Manifest / alignment report
→ Atomic publish to Drive
→ Studio 顯示試聽與狀態

## Speech Text Sanitizer
只做不改變語意的機械整理：
- 去除字幕標記，例如 >>。
- 正規化連續空白與重複標點。
- 去除 rolling caption 造成的「前段尾巴 = 下一段開頭」精確重複。
- 不改寫、不摘要、不重新翻譯。
- 專有名詞原封不動交給 TTS。

## 跨 segment 重複清理
現有英文 overlap cleanup 擴展到所有語言：
- token suffix/prefix exact match。
- Unicode character suffix/prefix exact match，供 Thai / Tamil 等語言。
- 只刪除完全相同且達安全長度的重複。
- 不做 fuzzy / semantic dedupe，避免誤刪講師真正的重複強調。

Manifest 記錄 removed_overlap / overlap_characters / source_segment_id。

## 語意區塊 Speech Blocks
不再一個字幕 cue 一次 TTS。每個 block 保存：
- source_segment_ids
- source_start / source_end
- text / text_sha256
- block_index

預設：
- 原影片停頓 > 1.5 秒可強制分 block。
- 句尾強標點 + 已有足夠內容時優先分 block。
- 英文 / 西文 / 印尼 / 越南約 350～500 chars。
- 泰文 / 泰米爾文約 260～400 chars。\n- 印地語約 300～450 chars。
- 目標約 2～5 blocks / minute，避免頻繁重新起音。

## TTS 生成
Edge：
- 每 block 一次生成。
- 同一堂同語言固定 voice / rate / pitch。
- 保存 block MP3 + boundary metadata。
- 網路失敗重試 3 次並退避。
- Edge 成功後不載入 GPU 模型。

MMS：
- Sindhi 正式主引擎。
- 其他六語只在手動 fallback 時使用。
- 使用目前永久 Kaggle Input 模型。

## 兩種輸出
A. <lang>.preview.mp3
- 人工試聽自然度。
- block 間只保留自然短停頓。
- 不要求與影片同長。

B. <lang>.mp3 + <lang>.wav
- 正式多語音軌。
- 每 block 優先從原 source_start 開始。
- 若上一 block 尚未結束，下一 block 往後順延。
- 保留可利用的原始停頓。
- 最後只補正常尾端到原影片總長。
- 若仍超過來源總長，標 needs_review，不截字。

## 時間軸自然度政策
允許：
- 只有累積 drift 時才做微幅速度補償，上限約 +8%。

禁止：
- 為短字幕 cue 強塞一句完整話。
- 大幅加速。
- 截斷語音。
- 把大段靜音全部堆在整堂尾端。

needs_review：
- 累積 drift > 5 秒。
- 完整音軌超過來源總長 > 3 秒。
- 任一 block 需要 >8% 加速才能跟上。
- 任一 block 生成為空或不可 decode。

## QA
文字 QA：
- source SHA256 / cleaned SHA256。
- segment coverage 100%。
- 沒有空 block。
- exact duplicate cleanup report。
- TTS 不可改翻譯內容。

音訊 QA：
- ffprobe 可 decode。
- duration > 0。
- 每 block 有音訊。
- 長靜音偵測。
- final duration / drift。
- block 數異常偵測。

Optional Deep QA：
- 抽樣前 / 中 / 後 30 秒 re-ASR。
- 與 Final text 語意比對。
- 母語者盲聽。
不預設每堂都跑，避免浪費 GPU/API。

## Drive 輸出
04_音檔/
- en.mp3
- en.wav
- en.preview.mp3
- en.tts_manifest.json
- th / es / id / vi / hi / ta 同格式

內部檔（檔案總覽預設隱藏）：
- <lang>.tts_checkpoint.json
- <lang>.tts_blocks.zip
- <lang>.alignment_report.json
- *.part.*.mp3

## Checkpoint / Resume
- 每完成 block 保存 checkpoint。
- block 以 source text SHA + voice profile 驗證。
- SHA / voice / engine 一致才 reuse。
- 不一致只重生受影響 block。
- 其他已成功語言不重做。

## Atomic Publish
1. 產 staging/<run_id>/...
2. QA。
3. 保存 revisioned manifest。
4. replace canonical <lang>.mp3 / wav / preview。
5. status = done。

失敗時：
- canonical 舊版保留。
- status = error / needs_review。
- staging 保留診斷資訊。

## Studio
每語言卡片：
- 語言。
- 正式文稿狀態。
- TTS engine / voice。
- 生成狀態。
- 試聽 Preview。
- 試聽正式音軌。
- 重新生成。
- 進階資訊。

一般使用者不需選 voice。進階設定才顯示 engine / voice / rate / pitch / force。

Hindi 顯示：Edge Natural / hi-IN-MadhurNeural；可在進階設定切換其他 hi-IN Neural voice。

## YouTube Auto-Dub 政策
只用於：
1. Naturalness benchmark。
2. 人工 A/B。
3. 使用者明確選擇 YouTube audio source。

預設正式 TTS 不再因發現 YouTube alternate audio 就跳過 SoulKey TTS。

## Kaggle Runtime Router
CPU：
- Edge Natural：en/th/es/id/vi/hi/ta。
- 字幕 / manifest / audio assembly。

GPU T4：
- ASR。
- local LLM。
- MMS Sindhi。
- 手動 MMS fallback。

若只做 en/th/es/id/vi/ta TTS，不申請 GPU。
若包含 sd，可拆成 Edge CPU + sd GPU 子工作。

## 狀態
每語言：
pending → queued → running → qa → done

例外：
needs_review / error / stale

TTS Stage 完成條件：
- 本堂所有 audio_enabled 語言均 done，或人工音檔已確認。
- 任一 needs_review → Stage needs_review。
- 任一 error → Stage error，但已完成語言保持 done。

## 上線
目前：
- 功能分支準備。
- main 正式版不切換。

當使用者說「可以上線」：
1. 同步最新 main。
2. 跑 unit tests。
3. P256-L01 七語 smoke。
4. merge feature → main。
5. TTS stage 預設切 Natural v2。
6. 跑一堂完整正式測試。
7. 驗證 Drive / Studio / checkpoint / status。
8. 舊 MMS 保留 fallback。

Rollback：
- 以單一 release commit 回復舊 runner。
- 新檔 QA 成功前不覆蓋舊 canonical。
