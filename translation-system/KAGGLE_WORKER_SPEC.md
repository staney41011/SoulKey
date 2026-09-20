# SoulKey｜Kaggle Worker 規格 v1.0

## 目的

Kaggle 是本專案的 GPU 執行環境，不是永久伺服器。

設計目標：

```text
啟動
→ 讀取指定工作
→ 執行指定 Stage
→ 寫回 Drive / Sheet
→ 紀錄結果
→ exit
```

不允許：

```text
啟動
→ while true 等待工作
→ 長時間空燒 GPU
```

---

## 1. Worker CLI

最終希望統一為：

```bash
python worker.py --task-id P253-L02 --stage asr
python worker.py --task-id P253-L02 --stage polish
python worker.py --task-id P253-L02 --stage finalize-zh
python worker.py --task-id P253-L02 --stage translate --lang en
# 英文人工定稿在 Web / 人工流程完成，不占 Kaggle GPU
python worker.py --task-id P253-L02 --stage translate-all
python worker.py --task-id P253-L02 --stage tts --lang en
```

保留目前既有：
- `runner.py`
- `polish_runner.py`

直到新 worker 完全驗證後再整合。

---

## 2. 啟動前 Doctor

GPU 工作執行前必須驗證：

- Python
- CUDA
- GPU
- FFmpeg
- ASR model
- Qwen model（若 stage 需要）
- Google OAuth
- Google Drive
- Google Sheet
- YouTube cookies（若 stage 需要）
- Chromium
- WPC provider
- Deno

Doctor 不應下載大型模型，除非明確執行 setup。

---

## 3. 模型保存

### ASR
`taiwan-breeze-asr-26`

### 中文校稿
`qwen3-4b`

永久模型優先從：

`/kaggle/input/`

尋找。

只有第一次建立資產時才允許從 Hugging Face 下載。

---

## 4. GPU 使用規則

- 只有 ASR / LLM / TTS 等需要 GPU 的 Stage 才使用 Kaggle GPU。
- metadata、Drive I/O、人工確認資料整理不應占用 GPU。
- 一個 notebook run 只處理有限任務。
- 預設 `--max-tasks 1`。
- 批次工作需顯式指定。
- 工作完成後 Python exit。
- 不做 background sleep / poll。

---

## 5. Runtime 預算

建議硬限制：

- metadata: 10 分鐘
- ASR 單堂: 60 分鐘
- 中文 AI 校稿單堂: 60 分鐘
- 翻譯單語言單堂: 45 分鐘
- translate-all 單堂: 120 分鐘
- TTS 單語言: 90 分鐘

若超時：
- status=error
- reason=timeout
- 保存現有 log
- exit non-zero

---

## 6. Checkpoint

長工作至少在以下階段保存 checkpoint：

ASR：
- audio_downloaded
- audio_normalized
- asr_finished
- uploaded

Polish：
- pass1_finished
- pass2_finished
- report_uploaded

Translation：
- 每完成一語言立即保存
- 不等五語全部完成才寫回

TTS：
- 每 segment / chunk 有可恢復紀錄

---

## 7. Idempotent

同一 Task + Stage 重跑時：

若 status=done：
- 預設 skip

使用：
`--force`

才重新執行。

final 類檔案不得被 force AI 流程覆蓋。

---

## 8. 工作完成後清理

可刪：
- YouTube 暫存音訊
- 16k WAV
- 模型以外的暫存檔
- 臨時 cookie file
- 中間 FFmpeg 文件

不可刪：
- Kaggle Input 永久模型
- Drive 輸出
- 任務 log

---

## 9. Secret

必要 Secret：

- GOOGLE_CLIENT_ID
- GOOGLE_CLIENT_SECRET
- GOOGLE_REFRESH_TOKEN
- YOUTUBE_COOKIES_B64

未來外部自動啟動可能還需要：
- Kaggle API credential（放 GitHub Secret / 安全後端，不放 Notebook Source）

任何 Secret：
- 不 print
- 不寫 log
- 不寫 JSON output
- 不寫 GitHub

---

## 10. Run Summary

每次 Kaggle run 最後必須輸出摘要：

```text
==================================================
SoulKey Worker Summary
Task: P253-L02
Stage: polish
Status: DONE
Elapsed: 00:17:42
GPU: Tesla T4
Output:
- zh-TW.polished.txt
- zh-TW.polished.srt
- polish_report.json
Uncertain: 10
==================================================
```

---

## 11. 自動結束

成功：
- exit code 0

失敗：
- 寫回錯誤狀態
- exit code 1

不得在完成後：
- sleep
- 等待新工作
- 保持 GPU session 活著

---

## 12. 未來網頁喚醒

未來流程：

```text
Web
→ Secure API
→ GitHub Actions workflow_dispatch
→ kaggle kernels push
→ Kaggle run
→ Worker
→ Drive/Sheet
→ exit
```

Kaggle 本身不需要等待網頁。

---

## 13. 目前已驗證基線

已驗證：
- Kaggle T4 可用
- Breeze ASR 永久模型可用
- Google OAuth / Drive / Sheet 可用
- YouTube Cookies + WPC + Chromium + Deno 可用
- Unlisted YouTube 可下載音訊
- Qwen3-4B 可在 T4 執行兩輪中文校稿
- Drive 可收到校稿結果

下一階段先完成：
1. 中文人工 final 機制
2. glossary learning
3. translate engine
4. TTS
5. 任務狀態回報與 Web 解鎖機制


---

## 14. 翻譯與 TTS 新規則

翻譯固定鏈：

```text
zh-TW.final.json
→ zh-TW.vernacular.json (AI Draft)
→ 人工白話文定稿 → zh-TW.vernacular.final.json
→ en.json (English Draft)
→ 人工英文定稿 → en.final.json
→ th/es/id/vi.json
```

測試期間若 final 尚未完成，可以顯式使用 `--allow-draft` 讓 `polish_report.json` 當來源；正式流程禁止。

白話化與翻譯共用 Qwen3-4B：
- 白話化：整篇逐 segment 處理，但保留前後文
- English：只能讀人工定稿後的 zh-TW.vernacular.final.json
- th/es/id/vi：只能讀人工確認後的 English Final pivot
- 每一段保留 id/start/end
- 文言、偈語、經典句若不確定，標記 review_required

TTS 第一版：
- en → facebook/mms-tts-eng
- th → facebook/mms-tts-tha
- es → facebook/mms-tts-spa
- id → facebook/mms-tts-ind
- vi → facebook/mms-tts-vie

每語言輸出：
- full WAV
- full MP3
- segment WAV zip
- tts manifest

TTS 目前採自然連續朗讀：
- 不調速
- 不做逐段時間對齊
- 不為了時間重新斷句
- 只要求整條音檔在原片總長內結束
- 比原片短時只在尾端補靜音
- 超過原片總長時不截斷，標記待人工確認


---

## 15. 人工英文定稿（非 GPU Stage）

English 翻譯完成後，Kaggle 必須停止於 English Draft，不得自動進入 th/es/id/vi。

Web 人工流程：
- 顯示 zh-TW.vernacular 與 en Draft 的逐 segment 對照
- 英文可人工修正
- 人工確認專有名詞英文譯法
- 將確認結果寫回 glossary
- 產生 en.final.json / txt / srt

只有 en.final 完成後，才允許再次喚醒 Kaggle 執行其他四語翻譯。


---

## 16. 人工白話文定稿（非 GPU Stage）

AI 白話化完成後，Kaggle 不得自動接著做 English。

Web 人工流程：
- 左側顯示 zh-TW.final 原文
- 右側顯示 zh-TW.vernacular Draft 並可修改
- 人工定稿後產生 zh-TW.vernacular.final.json / txt / srt
- English 只能以 vernacular final 為來源

---

## 17. 退回上一步與 stale 下游

Web 可將任務退回上一個 stage。

Worker / 後端規則：
- 不刪除既有檔案
- 下游產物標記 stale / needs_recheck
- stale final 禁止被後續 stage 讀取
- 人工 final 修改後建立新 revision
- 只有新 revision 再確認完成後，才能重新啟動下一個 GPU stage


---

## 18. 任務狀態回報協定

Kaggle / Worker 不得只靠 exit code 讓 Web 猜測結果。

每個正式 Stage 在生命週期中必須回報：

```text
queued → running → done
                 ↘ needs_review
                 ↘ error
```

若上游 revision 改變，下游既有成果改為：

```text
stale
```

### Worker 寫入時機

- GitHub / bridge 接受工作：`queued`
- Kaggle 真正開始執行：`running`
- 成功且無人工關卡：`done`
- 成功但需要人工定稿：`needs_review`
- Exception / timeout / 驗證失敗：`error`

### Web 解鎖

只有目前 Stage = `done`，下一個 Stage 的「執行」按鈕才可使用。

若 = `needs_review`：
- 不開放下一個 GPU Stage
- 只開放對應人工校正 / 定稿頁
- 人工 Final 保存成功後才寫 `done`

若 = `error`：
- 顯示錯誤摘要
- 只開放重跑

### 建議中央狀態紀錄

建立獨立狀態資料表，不與成果檔混在一起。至少欄位：
- task_id
- stage
- status
- run_id
- progress
- message
- started_at
- finished_at
- updated_at
- error_code
- error_message
- input_revision
- output_revision

Web 可透過 Apps Script / 安全 API 讀取，不直接碰 Kaggle Secrets。
