# SoulKey Translation System｜工作需求規格 v1.0

> 本文件先定義「Kaggle 後端工作流程」與「每一階段的輸入 / 輸出 / 完成條件」。
> 網頁僅作未來操作介面，**目前不以網頁為主，也不修改既有 DM 分享頁**。

## 0. 核心原則

1. 每一堂課必須可以「逐階段執行」，不能一次黑箱跑到底。
2. 每一階段都要有明確狀態：待處理 / 處理中 / 待人工確認 / 完成 / 錯誤。
3. 前一階段未完成，不得進入下一個依賴階段。
4. 所有 AI 產物不得覆蓋原始資料；原始 ASR 必須永久保留。
5. 中文逐字稿未「人工定稿」前，不得進入正式翻譯。
6. 專有名詞庫與知識庫為全期共用，且會持續累積。
7. Kaggle 僅在執行 GPU 工作時啟動；工作結束後程式應自然 exit，不做常駐輪詢。
8. 所有 Secret 只能放在 Kaggle Secrets / 安全後端 Secrets，不可寫入 GitHub、Sheet 或前端 JS。
9. 既有根目錄 `index.html` 為 DM 分享頁，任何翻譯系統開發不得修改。

---

## 1. 完整流程

```text
YouTube URL
  ↓
01 Metadata
  ↓
02 Audio Download
  ↓
03 ASR
  ↓
04 AI 中文校稿第一輪
  ↓
05 AI 中文複核第二輪
  ↓
06 異常詞／待人工確認整理
  ↓
07 人工中文定稿
  ↓
08 全文白話化（文言／古語 → 現代繁中）
  ↓
09 中文白話 → English Pivot
  ↓
10 English → Thai / Spanish / Indonesian / Vietnamese
  ↓
11 各語言人工確認
  ↓
12 字幕整理
  ↓
13 TTS
  ↓
14 音訊時間軸對齊
  ↓
15 完成影片
```

---

## 2. 任務識別

每一堂課必須有唯一 Task ID。

目前格式：

```text
P253-L01
P253-L02
P253-L03
P253-L04
```

欄位至少包含：

- task_id
- period
- lesson
- title
- youtube_url
- lecturer
- source_language
- asr_status
- zh_review_status
- en_status
- th_status
- es_status
- id_status
- vi_status
- subtitle_status
- audio_status
- video_status
- overall_progress
- updated_at
- note

---

## 3. Stage 01｜YouTube Metadata

### 輸入
- YouTube URL
- YouTube Cookies（必要時）

### 工作
- 驗證 URL
- 讀取影片標題
- 讀取影片長度
- 讀取頻道 / uploader
- 偵測講師名稱
- 套用講師別名規則

### 特殊規則
- 若辨識為「中和老師」，標準講師名稱一律寫成「翁樞紐」。

### 輸出
`00_來源資訊/source_info.json`

至少包含：
- task_id
- title
- lecturer
- lecturer_source
- duration
- youtube_url
- source_type
- saved_at

### 完成條件
- 可取得影片資訊
- title 非空
- lecturer 已標準化
- Sheet 已回填

---

## 4. Stage 02｜音訊下載

### 輸入
- YouTube URL
- Cookies
- WPC PO Token provider
- Chromium headless + no-sandbox
- Deno / yt-dlp EJS runtime

### 工作
- 下載最佳可用音訊
- 不保存原始完整影片
- FFmpeg 正規化成 16 kHz / mono WAV

### 輸出
Kaggle working 暫存：

`audio_16k_mono.wav`

### 完成條件
- 音訊可正常 decode
- 時長合理
- 任務完成後暫存音訊可刪除

---

## 5. Stage 03｜ASR

### 模型
`shooding/taiwan-breeze-asr-26`

### 執行環境
- Kaggle T4
- 優先使用永久掛載 Kaggle Input 模型

### ASR 要求
- language=zh
- 支援華語 + 台語混合語音
- 啟用 VAD
- 保留 segment start / end
- 專有名詞庫加入 initial_prompt
- 原始辨識結果不得被覆蓋

### 輸出
`01_中文逐字稿/`

- `zh-TW.txt`
- `zh-TW.srt`
- `segments.json`

### 完成條件
- segments > 0
- 每段有 start / end / text
- Sheet ASR = 完成

---

## 6. Stage 04～05｜AI 中文校稿

### 模型
目前：
`Qwen/Qwen3-4B`

### 第一輪
處理：
- 同音錯字
- 一般錯字
- 標點
- 斷句
- 成語
- 歷史典故
- 道場固定用語
- 仙佛 / 聖賢名稱
- 專有名詞

### 第二輪
必須比較：
- raw ASR
- 第一輪結果
- 前後文
- 專有名詞庫

第二輪目的：
- 抓第一輪漏掉的錯字
- 抓語意不通的同音拼接
- 抓固定稱謂 / 經典 / 成語
- 不確定內容列入 uncertain

### 禁止
AI 不得：
- 改變講者原意
- 自行補充教義
- 自行改寫成文章
- 把不確定台語硬猜成中文
- 刪除或新增 segment

### 輸出
- `zh-TW.polished.txt`
- `zh-TW.polished.srt`
- `zh-TW.readable.txt`
- `polish_report.json`

### polish_report.json 至少包含
- model
- segment_count
- changed_segment_count
- uncertain_count
- changes
- uncertain
- final segments

---

## 7. Stage 06｜異常詞與人工確認清單

所有以下情況都應進入待人工確認：

- AI 兩輪仍無法判定
- 台語 / 閩南語俗諺
- 人名、地名、特殊稱謂
- 仙佛名稱不確定
- 經典引文疑似錯誤
- 語意明顯不通但無高信心替代
- 同一詞前後版本不一致
- 仍含已知 ASR 高風險字串

每筆 uncertain 至少保存：

- segment_id
- start
- end
- raw_text
- polished_text
- uncertain_phrase
- context_before
- context_after
- suggested_candidates
- human_status
- human_correction

---

## 8. Stage 07｜人工中文定稿

人工確認後，產生不可被 AI 自動覆蓋的正式版本：

- `zh-TW.final.txt`
- `zh-TW.final.srt`
- `zh-TW.final.json`

### 中文定稿規則
只有下列條件全部成立，才能標記完成：

- uncertain_count = 0，或每個 uncertain 已明確人工確認
- 所有人工修改已寫回
- 專有名詞已確認
- 字幕時間軸未被破壞
- final 版本已保存

### 鎖定
中文 final 建立後：
- AI 再重跑不得覆蓋 final
- 若需修改 final，必須建立新 revision

---

## 9. 專有名詞資料庫

專有名詞資料不只保存「正確字」，也要保存 ASR 常見誤辨。

### 建議欄位
- term_id
- canonical_zh
- category
- description
- aliases
- common_asr_errors
- confidence
- source
- source_task_id
- human_verified
- English
- ไทย
- Español
- Bahasa Indonesia
- Tiếng Việt
- translation_locked
- created_at
- updated_at

### 類別
至少包含：
- 道場專有名詞
- 道場稱謂
- 仙佛 / 聖賢名稱
- 人物 / 講師
- 佛規禮節
- 一貫道經典 / 訓文
- 佛教
- 儒家
- 道家 / 道教
- 基督宗教
- 台語 / 閩南語
- 歷史典故
- 成語

### 學習機制
人工把：

`前嫌 → 前賢`

確認後，系統應保存：
- canonical = 前賢
- common_asr_error += 前嫌

未來：
- ASR initial_prompt 使用 canonical
- AI 校稿使用 canonical + aliases + common_asr_errors
- 翻譯使用 canonical + 鎖定翻譯

---

## 10. 經典／知識庫

與「專有名詞庫」分離。

知識庫用來提供上下文，不做強制字串替換。

建議欄位：
- item_id
- title
- tradition
- source_name
- chapter
- original_text
- explanation
- keywords
- related_terms
- verified
- source_reference

用途：
- 判斷典故
- 判斷經文引用
- 判斷人物名稱
- 協助 AI 產生候選修正

---

## 11. Stage 08～10｜白話化 + English Pivot + 五語翻譯

目標語言：
- English
- ไทย
- Español
- Bahasa Indonesia
- Tiếng Việt

### 11.1 中文白話化

正式來源優先使用：
`zh-TW.final.json`

整篇逐字稿先轉為：
- `zh-TW.vernacular.txt`
- `zh-TW.vernacular.srt`
- `zh-TW.vernacular.json`

規則：
- 已是現代白話的句子儘量維持
- 文言文、古語、偈語、凝縮句轉成忠實現代白話
- 不摘要、不刪減、不增加教義
- 不確定經文／台語／仙佛稱謂標記 review_required
- 原中文永久保留，不被白話版覆蓋

### 11.2 English Pivot

英文是所有外語翻譯的樞紐語言。

唯一流程：

```text
繁中 final
→ 繁中白話 vernacular
→ English
→ Thai / Spanish / Indonesian / Vietnamese
```

禁止：
- 中文直接翻泰文
- 中文直接翻西文
- 中文直接翻印尼文
- 中文直接翻越南文

### 11.3 翻譯規則

- 保留 segment id
- 保留 start/end
- 不自行摘要
- 語義自然，但不改變教義
- 專有名詞依鎖定翻譯
- 經典名稱按目標語言慣用名稱
- 若無標準翻譯，標記 review_required
- English 必須以 zh-TW.vernacular 為來源
- th/es/id/vi 必須以 English 為來源

### 每個語言輸出
- `<lang>.txt`
- `<lang>.srt`
- `<lang>.json`

---

## 12. Stage 11｜翻譯人工確認

每個語言需獨立狀態：

- 待翻譯
- AI完成
- 待人工確認
- 完成

任一語言不可因其他語言完成而自動標完成。

---

## 13. Stage 12～15｜字幕 / TTS / 影片

### 字幕
- 以各語言 final transcript 建立
- 每行避免過長
- 不破壞原時間軸語意

### TTS
- 語言各自生成
- 保留 segment 對應
- 第一版使用 Meta MMS-TTS：eng / tha / spa / ind / vie
- 產出完整 WAV、MP3、逐 segment WAV 壓縮包與 manifest
- 第一版完整音檔為連續朗讀版；影片配音對齊另由下一階段處理
- 未來可支援指定講師聲線
- MMS-TTS 授權為 CC-BY-NC 4.0；若未來涉及商業用途，必須先更換或重新確認 TTS 授權

### 音訊總長規則（目前版本）
- 暫時不做逐 segment 對齊
- 不調整語速
- 不為了時間重新斷句
- 只要求完整 TTS 在原影片總長內結束
- 若 TTS 較短：只在尾端補靜音，讓輸出音軌與原片總長一致
- 若 TTS 超過原片總長：不得截斷內容，標記 needs_review / 待人工確認
- 每段 segment WAV 仍保留，供未來精細對齊使用

### 完成影片
每語言獨立輸出。

---

## 14. 錯誤與重跑

每一 stage 必須：
- 可獨立重跑
- 有 force 參數
- 有 status
- 有錯誤訊息
- 不破壞前一版本

建議：
```text
pending
running
needs_review
done
error
```

---

## 15. 日誌

每個 Task 要記錄：
- run_id
- task_id
- stage
- started_at
- finished_at
- elapsed_seconds
- GPU / CPU
- model
- result
- error
- files_written

未來可計算每週 Kaggle GPU 使用時間。

---

## 16. 完成標準

一堂課只有以下都完成才算「整堂完成」：

- Metadata
- ASR
- 中文 AI 校稿
- 中文人工定稿
- 五語翻譯
- 五語人工確認
- 字幕
- TTS
- 完成影片

---

## 17. 開發優先順序

### Phase A｜先把 Kaggle 做完整
1. ASR 穩定
2. AI 中文兩輪校稿
3. uncertain 整理
4. 人工修正檔匯入
5. 中文 final 鎖定
6. 詞庫讀寫
7. 五語翻譯
8. TTS
9. 影片輸出

### Phase B｜再做 Web
Web 只負責：
- 建立任務
- 顯示進度
- 顯示字幕
- 人工修改
- 詞庫管理
- 觸發 stage

Web 不重新實作模型邏輯。

---

## 18. 不可修改區域

以下視為既有 DM 系統：

- repo 根目錄 `index.html`
- `images/`
- `scripts/download_images.js`
- `.github/workflows/update_dm.yml`

翻譯系統只能使用：
- `translation-system/`
- 未來 `studio/`
- 新增的獨立 workflow

不得讓翻譯系統破壞 DM 分享頁。
