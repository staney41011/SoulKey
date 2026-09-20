# SoulKey Studio

這個資料夾是「打開心靈的鎖匙｜全球翻譯工作台」的獨立前端。

## 重要隔離規則

- **不要修改 repo 根目錄的 `index.html`**：那是既有 DM 分享頁。
- **不要修改 `.github/workflows/update_dm.yml`**：那是既有 DM 更新流程。
- Studio 一律使用 `/studio/` 路徑。
- GPU／翻譯工作流使用新的獨立 workflow 名稱。

GitHub Pages URL:

`https://staney41011.github.io/SoulKey/studio/`

## v0.1

目前為前端原型：
- 建立 YouTube 任務
- 流程總覽
- 中文校稿介面
- 待人工確認介面
- 專有名詞庫 UI
- 經典知識庫規劃
- GPU 按需啟動狀態設計

`config.js` 的 `apiBaseUrl` 留空時使用 prototype mode。
敏感 Token 絕不可寫入任何 studio 前端檔案。
