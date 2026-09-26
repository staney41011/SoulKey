# Gemini Shadow 版

狀態：**未上線 production**。

目前 Gemini 版與正式 Qwen/Kaggle 流程完全隔離。

## 模型

- 文字：`gemini-3.8-flash`
- TTS：`gemini-3.8-flash-tts`

## 已實作

1. English Final → Thai / Spanish / Indonesian / Vietnamese / Sindhi / Tamil
2. Structured Output，固定 segment id
3. Gemini translation QA
4. QA fail → 單段自動 repair → 再 QA
5. 本地 target-script guard
6. 429 / 5xx retry
7. 中文第二層語意校稿
8. 專有名詞 RAG，只取本段命中的詞
9. LOCKED 中文詞本地 guard，Gemini 不得改壞
10. Gemini TTS WAV adapter
11. Shadow CLI，不寫正式 Drive

## 測試層級

### 自動單元測試

Workflow：

`SoulKey Gemini Shadow Validate`

不需要 API key，使用 fake transport，檢查：
- Structured Output request
- usage parsing
- 429 retry
- WAV decoding
- missing key fail-closed
- segment id 完整性
- 泰文 script guard
- glossary retrieval
- translate + QA pass
- wrong-language → repair → QA pass
- LOCKED term guard

### 真 API Shadow Smoke

Workflow：

`SoulKey Gemini Shadow Live Smoke`

需要 GitHub Repository Secret：

`GEMINI_API_KEY`

這個 workflow：
- 不讀正式 Drive
- 不寫 Google Sheet
- 不啟動 Kaggle
- 不覆蓋任何正式翻譯
- 使用 fixture 跑六語翻譯 + QA
- 跑中文第二層語意校稿 + glossary RAG
- 選配一小句 Gemini TTS
- 結果只保留為 7 天 GitHub artifact

## 上線條件

只有以下全部通過才切換 production：

1. Shadow unit tests 全綠
2. 六語 live smoke 全綠
3. TTS smoke 為有效 RIFF/WAV
4. 所有回傳 segment id 完整
5. 任何 QA fail 都不得靜默寫入正式輸出
6. 先用一堂已完成人工 English Final 的課程做 shadow comparison
7. 人工抽看 Gemini 與現行 Qwen 結果後再切 feature flag

正式切換前，`translate_runner.py` 與 `web_job_worker.py` 維持 Qwen production，不引用 Gemini Shadow。
