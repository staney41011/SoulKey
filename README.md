# SoulKey｜打開心靈的鎖匙

本 Repository 包含課程分享頁、全球翻譯工作台與 Kaggle 翻譯／配音工作流程。

## 接手前請先閱讀

**[SOULKEY_OPERATIONS_LOG.md｜正式操作日誌、修復紀錄與第259期64語交付狀態](SOULKEY_OPERATIONS_LOG.md)**

這份日誌記錄 GitHub PR、GitHub Actions Run ID、現行系統路由、既有資料保護規則、已完成／尚待驗證的工作。不能用 ChatGPT 對話記憶、GitHub Actions 綠燈或「已派工」訊息，替代實際 Drive 文稿／音檔驗收。

## 各系統位置

- [SoulKey 全球翻譯工作台](https://staney41011.github.io/SoulKey/studio/)
- [Studio 前端](studio/)
- [Google Apps Script 原 Bridge](bridge/apps-script/)
- [Kaggle／翻譯與配音 Worker](translation-system/)
- [Cloud Run 控制中心原始碼](cloud-bridge/)
- [正式 Kaggle Web Job](.github/workflows/kaggle_web_job.yml)
- [翻譯工作流程需求規格](translation-system/WORKFLOW_REQUIREMENTS.md)

## 開發與交付原則

1. 每次修復要有 GitHub PR、可核對的測試，以及操作日誌記錄。
2. 修改 GitHub 原始碼**不代表** Apps Script 或 Cloud Run 已重新部署。
3. 翻譯／音檔任務只有在來源與 QA 正確、Google Drive 檔案存在且能讀回後才能標示完成。
4. 保護原始文稿、人工英文定稿、既有 QA、音檔及版本；不得因單次錯誤覆蓋。
5. 不把 Bridge Key、OAuth Token、GitHub Token、Cookies 或其他 Secret 寫進 GitHub。
6. Repo 根目錄 `index.html` 是既有分享頁；全球翻譯工作台位於 `/studio/`，不可互相覆蓋。
