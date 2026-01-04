const fs = require('fs');
const https = require('https');
const path = require('path');

// 【關鍵修正】網址後面一定要有 ?type=json，否則會拿到 HTML 網頁
const API_URL = 'https://script.google.com/macros/s/AKfycbwvNwOn8QwvH-agggTWm6ZZUosmCPDuGUpSbckc8DFahBP9fiHLfPCBCIlWMt9p4V3V/exec?type=json';
const IMG_DIR = 'images';

// 確保圖片目錄存在
if (!fs.existsSync(IMG_DIR)){
    fs.mkdirSync(IMG_DIR);
}

// 下載函數
const download = (url, dest, cb) => {
  const file = fs.createWriteStream(dest);
  https.get(url, function(response) {
    if (response.statusCode !== 200) {
      fs.unlink(dest, () => {}); // 刪除空檔案
      if (cb) cb(`下載失敗，HTTP 狀態碼: ${response.statusCode}`);
      return;
    }
    response.pipe(file);
    file.on('finish', function() {
      file.close(cb);
    });
  }).on('error', function(err) {
    fs.unlink(dest, () => {});
    if (cb) cb(err.message);
  });
};

console.log(`正在連線至 API: ${API_URL}`);

https.get(API_URL, (res) => {
  let body = "";
  res.on("data", (chunk) => { body += chunk; });
  res.on("end", () => {
    try {
      // 嘗試解析 JSON
      // 如果這裡報錯，通常是因為 API_URL 沒加 ?type=json，回傳了 HTML
      const json = JSON.parse(body);
      
      if (json.items.length === 0) {
        console.log("警告: API 回傳的圖片列表是空的！");
        process.exit(0); // 正常結束，但沒東西可下載
      }

      const dataJsonPath = path.join(IMG_DIR, 'data.json');
      
      // 準備本地資料
      const localData = { ...json };
      localData.items = json.items.map(item => {
        const filename = `${item.lang}.png`; 
        return {
          ...item,
          imageUrl: `images/${filename}`, 
          localFilename: filename
        };
      });

      // 寫入 data.json
      fs.writeFileSync(dataJsonPath, JSON.stringify(localData, null, 2));
      console.log(`已更新 data.json，共 ${localData.items.length} 筆資料`);

      // 下載所有圖片
      let downloadCount = 0;
      localData.items.forEach(item => {
        const downloadUrl = item.downloadUrl; 
        const dest = path.join(IMG_DIR, item.localFilename);
        
        download(downloadUrl, dest, (err) => {
          if(err) {
            console.error(`❌ 下載失敗 [${item.lang}]:`, err);
            process.exit(1); // 發生錯誤直接讓 Action 失敗
          } else {
            console.log(`✅ 下載完成: ${item.lang}`);
            downloadCount++;
            // 檢查是否全部下載完畢
            if (downloadCount === localData.items.length) {
              console.log("所有圖片下載完畢！");
            }
          }
        });
      });

    } catch (error) {
      console.error("❌ 解析資料失敗！可能原因：");
      console.error("1. API 網址結尾忘了加 ?type=json");
      console.error("2. Google Apps Script 部署權限不是 'Anyone' (所有人)");
      console.error("原始錯誤:", error.message);
      console.log("API 回傳內容開頭:", body.substring(0, 100)); // 印出前100字來除錯
      process.exit(1); // 讓 Action 顯示紅燈失敗
    };
  });
});
