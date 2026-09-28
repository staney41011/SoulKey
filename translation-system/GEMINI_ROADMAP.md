# Gemini API 後續工作排程

本文件是「打開心靈的鎖匙」翻譯系統在既有 Kaggle / Qwen3-4B / Taiwan Breeze 架構之上的 Gemini API 導入順序。

原則：
- 先使用 Gemini API Free Tier 做品質提升。
- Taiwan Breeze 保留為中文 ASR 主力。
- Qwen3-4B 保留為 Kaggle 本地備援，不移除。
- English Final 仍保留人工定稿。
- English Final 之後的目標語言不再要求人工確認。
- 所有 Gemini 輸出仍需通過本地程式驗證，不盲信模型。

## P1｜Gemini 多語正式翻譯

來源固定使用 `en.final.json`。

目標語言：
- Thai (th)
- Spanish (es)
- Indonesian (id)
- Vietnamese (vi)
- Sindhi (sd)
- Tamil (ta)

設計：
1. Gemini 為正式主翻譯引擎。
2. 使用 Structured Output 強制每個 segment 保留 id / start / end。
3. Qwen3-4B 作 API 失敗、配額不足、429、暫時不可用時的 fallback。
4. 不允許直接 fallback 回英文原文後送進 TTS。
5. 各語言互相隔離，單一語言失敗不得中止其他語言。

## P2｜Gemini 翻譯 QA ＋ 自動修復

每個目標語言翻譯完成後，自動檢查：
- 是否完整保留原意
- 是否漏譯
- 是否多加原文沒有的內容
- 是否整段或局部仍為英文 / 中文
- 專有名詞是否違反 LOCKED glossary
- 是否適合自然口語朗讀
- segment id / 數量 / 時間軸是否完整

處理策略：
1. Gemini QA 回傳結構化 JSON。
2. pass=true → 直接進 TTS。
3. pass=false → 只重翻異常 segment。
4. 修復後重新 QA。
5. 單一語言最後仍失敗 → 記錄 error，其他語言繼續。

## P3｜TTS

Meta MMS-TTS / VITS 作正式 production 語音引擎；Gemini TTS 保留為可選高品質模式，不作預設。

目標：
- English
- Thai
- Spanish
- Indonesian
- Vietnamese
- Sindhi
- Tamil

要求：
- 先完成文本 QA 才能送 TTS。
- 各語言獨立執行與重試。
- 單一語言失敗不阻擋其他語言。
- 保留完整 MP3 / WAV / manifest。
- 正式批次音訊不消耗 Gemini TTS API 額度。
- Gemini TTS 僅在未來明確選擇「高品質語音模式」時使用。

## P4｜Gemini 中文第二層語意校稿＋資料庫術語學習

這一層位於：

Taiwan Breeze ASR
→ Qwen 基礎中文校稿
→ Gemini 語意校稿
→ 人工中文 Final

### 專有名詞資料來源

控制中心：
`專有名詞庫!A2:J500`

目前欄位：
- 中文原詞
- 類別
- 中文說明/語境
- English
- ไทย
- Español
- Bahasa Indonesia
- Tiếng Việt
- 鎖定翻譯
- 備註

後續需擴充：
- Sindhi
- Tamil
- 別名 / 常見誤聽
- 典型正確例句
- 來源 / 依據
- 最後更新時間
- 狀態（LOCKED / preferred / candidate）

### 執行方式（RAG，不是模型權重訓練）

每次校稿或翻譯前：
1. 先掃描當前 segment 的可能專有名詞。
2. 從「專有名詞庫」取回相關詞條。
3. LOCKED 詞條以硬規則放入 Gemini prompt。
4. preferred 詞條作優先建議。
5. Gemini 不得自行改寫 LOCKED 詞。
6. 未知但疑似重要的新詞，回傳為 `term_candidate`，不可直接鎖定。

### 自我累積 / 學習回饋

利用人工 Final 形成長期記憶：
- AI 中文稿 vs 人工中文 Final
- AI English vs 人工 English Final
- 被人工修改的專有名詞
- 固定稱謂、宗教術語、經典名稱、人物稱呼

這些差異轉成「修正案例」，寫入資料庫。
未來遇到相同或相似詞語時，先取回歷史案例再交給 Gemini。

這是 retrieval / RAG 式持續學習：
- 資料庫更新後下一次任務立即生效
- 不需要重新訓練 Gemini
- 不會因模型版本更換而失去本專案詞庫
- 可追蹤、可修改、可撤銷

### 安全規則

- Gemini 不能自動把新詞直接設成 LOCKED。
- 新詞只可先進 candidate。
- 已存在 LOCKED 詞與人工 Final 優先權最高。
- Gemini 建議不得覆蓋人工 Final。
- 所有 API 回覆需做 schema / 語言 / segment 完整性驗證。

## Gemini 導入順序

1. P1 多語正式翻譯
2. P2 翻譯 QA + 自動修復
3. P3 Gemini TTS
4. P4 中文第二層語意校稿 + 資料庫術語 RAG

每完成一項先用 P254-L03 做回歸測試，再擴到新課程。


## 2026-09-27 — Gemini-first production ownership

SoulKey production now routes every AI-capable stage to Gemini by default.

### Gemini-owned stages

- Primary Traditional Chinese transcript:
  Taiwan-Breeze ASR on Kaggle GPU, chosen specifically to retain Mandarin + Taigi
  code-switching support. If Taiwan-Breeze fails, `gemini_source_runner.py`
  may be used as an emergency source fallback.
- Chinese semantic polish:
  `gemini_text_production_runner.py --stage polish`.
- Vernacular Traditional Chinese rewrite:
  `gemini_text_production_runner.py --stage vernacular`.
- English draft translation:
  `gemini_text_production_runner.py --stage en`.
- Six-language translation from approved `en.final.json`:
  `gemini_multi_production_runner.py`.
- Multilingual semantic QA and targeted repair:
  built into `gemini_multi_production_runner.py`.
- Multilingual TTS is intentionally not Gemini-owned in production.
  Production audio uses `tts_runner.py` + Meta MMS-TTS / VITS on Kaggle GPU.
  `gemini_tts_production_runner.py` remains available as an optional
  high-quality cloud voice path.

### Non-Gemini responsibilities kept intentionally

- YouTube metadata / real caption-track existence: deterministic YouTube I/O.
- Human Final gates: Chinese, vernacular, and English approval remain human.
- Structural/local QA: Python validates IDs, missing text, scripts, and numbers.
- Google Drive / Sheets / checkpoint / status management: infrastructure code.
- Taiwan-Breeze: primary production ASR.

### Default models

- Bulk text work: `gemini-3.1-flash-lite`
- YouTube video understanding: `gemini-3.8-flash`
- Targeted stronger repair: `gemini-3.8-flash` with Flash-Lite fallback
- Production TTS: Meta MMS-TTS / VITS
- Optional high-quality cloud TTS: `gemini-3.8-flash-lite-tts`

The web worker routes language intelligence stages to Gemini by default.
Production TTS is routed to Meta MMS and receives Kaggle GPU allocation.
`zh/asr` also retain GPU allocation because the Taiwan-Breeze emergency
fallback may need CUDA.


## 2026-09-28 — Production TTS ownership

Final production split:

- Gemini: YouTube understanding, Chinese semantic polish, vernacular rewrite,
  English translation, six-language translation, semantic QA, targeted repair.
- Python: deterministic QA, orchestration, subtitles, checkpoints, Drive/Sheets.
- Taiwan-Breeze: ASR fallback when Gemini video understanding cannot be used.
- Meta MMS-TTS / VITS: default seven-language audio generation on Kaggle GPU.
- Gemini TTS: optional high-quality mode only; never required for normal batch
  production and never allowed to block normal production because of API quota.


## 2026-09-28 — Taiwan-Breeze-first production ASR

The production source order is now:

1. Taiwan-Breeze ASR on Kaggle GPU.
2. Gemini YouTube understanding only as an emergency source fallback.
3. Gemini semantic polish runs after the transcript is produced.
4. Human Chinese Final remains the authoritative gate.

This keeps Taigi / Mandarin code-switching support in the primary speech
recognition path while reserving Gemini for semantic correction, translation,
QA, and targeted repair.
