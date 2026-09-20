# SoulKey Studio Bridge（Google Apps Script）

這是一個最小化的安全轉接層：

```
SoulKey Studio (GitHub Pages)
  → Google Apps Script Web App
  → GitHub Actions
  → Kaggle
```

目前只允許 `action=smoke`，也就是觸發：

```
.github/workflows/kaggle_run_bridge_test.yml
```

不會呼叫正式 ASR／翻譯／TTS 工作。

## 1. 建立 GitHub Fine-grained PAT

只授權 `staney41011/SoulKey`。

需要能觸發 GitHub Actions workflow 的權限。請將 token 只放在 Apps Script 的 Script Properties，不要放進 GitHub repo 或 Studio 前端。

## 2. 建立 Apps Script

建立新的 Google Apps Script 專案，把 `Code.gs` 貼進去。

在「專案設定 → 指令碼屬性」新增：

- `GITHUB_TOKEN` = GitHub fine-grained PAT
- `BRIDGE_KEY` = 自己產生的一組長隨機字串

## 3. 部署為 Web App

- 執行身分：我
- 存取權：任何人
- 部署後取得 `/exec` Web App URL

公開入口本身不含 GitHub Token。每次請求還必須帶正確的 `BRIDGE_KEY`。

## 4. SoulKey Studio

到「系統狀態 → 網頁橋樑測試」：

- 貼上 Apps Script Web App URL
- 輸入同一組 BRIDGE_KEY
- 按「送出橋樑測試」

BRIDGE_KEY 不會寫進 GitHub；Studio 只保留在目前瀏覽器分頁的 sessionStorage。


## 任務狀態回報

控制中心試算表現在新增：

```
執行狀態
```

欄位：
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

新版 `Code.gs` 支援：
- `action=smoke`：原本 GitHub → Kaggle 測試
- `action=status_health`：確認狀態表可讀
- `action=status_batch`：依 task_id 批次讀取最新 stage 狀態

Studio 會透過 hidden iframe + `postMessage` 接收結果，避免把 GitHub Token 暴露到前端。

### 更新既有 Apps Script 部署

GitHub 內的 `bridge/apps-script/Code.gs` 更新後，Google Apps Script 不會自動同步。

請：
1. 將最新版 `Code.gs` 全部貼回 Apps Script。
2. 儲存。
3. 部署 → 管理部署作業 → 編輯。
4. 建立新版本並重新部署。
5. Web App URL 可維持同一個 `/exec` URL。

不用更換 `GITHUB_TOKEN` 或 `BRIDGE_KEY`。
