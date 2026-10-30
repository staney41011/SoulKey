// SoulKey 舊架構 + Firebase：Google Apps Script 是唯一正式 Bridge。
// GitHub Actions/Kaggle 執行翻譯與配音；Sheets/Drive 保留原授權及檔案。
// Firebase Hosting/Realtime Database 只加強控制中心，不取代人工定稿。
// 禁止把 OAuth、Firebase 管理密鑰、YouTube Cookies、GitHub/Kaggle Token 放入前端。
window.SOULKEY_CONFIG = {
  apiBaseUrl: "",
  bridgeEndpoint: "https://script.google.com/macros/s/AKfycbyyMjEUqDdhsXWwCWKRTjpyhzdrdXnKhJYZIyiQ-QblOR_nhUdxtv9tqujw5VHkbyZ3/exec",
  legacyKaggleBridgeEndpoint: "https://script.google.com/macros/s/AKfycbyyMjEUqDdhsXWwCWKRTjpyhzdrdXnKhJYZIyiQ-QblOR_nhUdxtv9tqujw5VHkbyZ3/exec",
  firebaseHostingUrl: "https://soulkey-control-2026.web.app/",
  reviewCacheBaseUrl: "https://raw.githubusercontent.com/staney41011/SoulKey/main/studio-review-cache",
  mode: "legacy-firebase",
  version: "0.1.3"
};
