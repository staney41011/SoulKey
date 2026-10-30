// SoulKey：Apps Script + GitHub + Kaggle；正式流程不依賴 GCP/Firebase。
// GitHub Actions/Kaggle 執行翻譯與配音；Sheets/Drive 保留原授權及檔案。
// 禁止把 OAuth、Firebase 管理密鑰、YouTube Cookies、GitHub/Kaggle Token 放入前端。
window.SOULKEY_CONFIG = {
  apiBaseUrl: "",
  bridgeEndpoint: "https://script.google.com/macros/s/AKfycbyyMjEUqDdhsXWwCWKRTjpyhzdrdXnKhJYZIyiQ-QblOR_nhUdxtv9tqujw5VHkbyZ3/exec",
  legacyKaggleBridgeEndpoint: "https://script.google.com/macros/s/AKfycbyyMjEUqDdhsXWwCWKRTjpyhzdrdXnKhJYZIyiQ-QblOR_nhUdxtv9tqujw5VHkbyZ3/exec",
  firebaseHostingUrl: "",
  reviewCacheBaseUrl: "https://raw.githubusercontent.com/staney41011/SoulKey/main/studio-review-cache",
  mode: "legacy-kaggle",
  version: "0.1.4"
};
