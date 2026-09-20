# 打開心靈的鎖匙｜全球翻譯系統

這個資料夾是 Kaggle / Colab 共用的雲端翻譯 Runner。

目前 v1 已包含：

1. 讀取「全球翻譯控制中心」Google Sheet
2. 從 YouTube 網址自動抓影片標題
3. 從影片標題/說明欄尋找講師，找不到才使用頻道/上傳者
4. 下載 YouTube 音訊
5. 使用 `shooding/taiwan-breeze-asr-26` + faster-whisper 進行中文/台語 ASR
6. 產出 `zh-TW.txt`、`zh-TW.srt`、`segments.json`
7. 將成果寫回該期、該堂課的 Google Drive 資料夾
8. 即時更新 Sheet 的 ASR 狀態與最後更新時間
9. 已完成任務預設跳過，可在 Kaggle 斷線後續跑
10. ASR 模型支援永久掛載；優先使用 Kaggle Input，不重複下載

## 模型永久保存

`shooding/taiwan-breeze-asr-26` 約 3.09 GB。

第一次執行：

```bash
python translation-system/prepare_model.py
```

模型會下載到：

```text
/kaggle/working/persistent-model/taiwan-breeze-asr-26
```

第一次下載完成後，在 Kaggle：

1. Save Version / Save & Run All
2. 保存 Notebook Output
3. 將該 Output 建成/掛成私人 Input（Dataset 或 Notebook Output）
4. 之後 Runner 會自動掃描 `/kaggle/input` 找 `model.bin + config.json`
5. 找到後直接載入，不再從 Hugging Face 下載

也可設定 `ASR_MODEL_PATH` 指向指定永久模型資料夾。

只有找不到永久模型時，Runner 才會自動回退到 Hugging Face 下載。

## Kaggle 必要設定

Notebook 必須：

- Accelerator：GPU（T4 即可）
- Internet：On
- GitHub 可讀取 `staney41011/SoulKey`

Kaggle Secrets 建立以下三個 Secret：

- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_REFRESH_TOKEN`

選用：

- `YOUTUBE_COOKIES_B64`
  - 只有 YouTube 在 Kaggle IP 要求登入/驗證時才需要。
  - 內容是 Netscape cookies.txt 的 base64。
  - 絕對不要 commit 到 GitHub。

## 為什麼不用 Service Account

本專案目前的主資料夾位於個人「我的雲端硬碟」。
Runner 使用「使用者 OAuth refresh token」，讓上傳檔案直接由你的 Google 帳戶擁有。

## Google OAuth 一次性設定

1. Google Cloud 建立一個 Project。
2. 啟用 Google Drive API 與 Google Sheets API。
3. OAuth consent screen 設定你的 Google 帳號。
4. 建立 OAuth Client ID，類型選 Web application。
5. Authorized redirect URI 加入：
   `https://developers.google.com/oauthplayground`
6. OAuth consent screen 建議切到 **In production**。
7. 打開 OAuth 2.0 Playground。
8. 右上齒輪：
   - Use your own OAuth credentials：ON
   - Access type：Offline
   - 輸入自己的 Client ID / Client Secret
9. Scope 輸入：
   - `https://www.googleapis.com/auth/drive`
   - `https://www.googleapis.com/auth/spreadsheets`
10. Authorize APIs → Exchange authorization code for tokens。
11. 將得到的 refresh token 放進 Kaggle Secret `GOOGLE_REFRESH_TOKEN`。

請勿把 OAuth Client Secret 或 Refresh Token 放進 GitHub、Google Sheet、Notebook 原始碼或對話訊息。

## Kaggle 執行

```bash
git clone https://github.com/staney41011/SoulKey.git /kaggle/working/SoulKey
cd /kaggle/working/SoulKey
pip install -q -r translation-system/requirements.txt
```

先跑 Doctor：

```bash
python translation-system/doctor.py
```

先只測 YouTube metadata：

```bash
python translation-system/runner.py --stage metadata --period 253 --max-tasks 4
```

如果 Sheet 的「課程名稱（自動）」與「講師（自動）」成功回填，再跑 ASR：

```bash
python translation-system/runner.py --stage asr --period 253 --max-tasks 1
```

第一堂成功後，再一次跑四堂：

```bash
python translation-system/runner.py --stage asr --period 253 --max-tasks 4
```

## 斷點續跑

ASR 欄位為「完成」的課程預設不再重跑。

需要強制重跑：

```bash
python translation-system/runner.py --stage asr --period 253 --max-tasks 1 --force-asr
```

需要重新抓 YouTube 標題/講師：

```bash
python translation-system/runner.py --stage metadata --period 253 --max-tasks 4 --force-metadata
```

## Drive 輸出

每堂課：

```text
00_來源資訊/
  source_info.json

01_中文逐字稿/
  zh-TW.txt
  zh-TW.srt
  segments.json
```

下一階段會加入：

- 中文逐字稿 AI 校正
- 專有名詞鎖定
- EN / TH / ES / ID / VI 五語翻譯
- 五語 TTS
- 音訊時間軸對齊
- 完整配音影片
